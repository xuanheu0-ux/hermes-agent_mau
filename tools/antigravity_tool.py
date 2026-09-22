#!/usr/bin/env python3
"""Antigravity managed-agent delegation tool (Gemini API ``Interactions API``).

Delegates a whole task to Google's managed Antigravity agent
(``antigravity-preview-09-2026``, the same harness as the Antigravity 2.0 IDE)
over the Gemini API's Interactions API. One call = one agent run in Google's
hosted Linux sandbox with its own filesystem/shell/web tools, optional remote
MCP servers and inline file sources; only the final report comes back. This is
task-level delegation, not a token-level model provider: Hermes' own tool loop
stays in this process while the remote agent does the legwork.

Preview API shape (docs: ai.google.dev/gemini-api/docs/antigravity-agent):
``POST {base}/interactions`` with ``x-goog-api-key``; interaction ``status`` is
``completed`` / ``failed`` / ``in_progress`` / ``incomplete`` (budget hit —
continue with ``previous_interaction_id`` + the returned ``environment_id``).
The agent rejects ``temperature``/``top_p``/``top_k``/``stop_sequences``/
``max_output_tokens`` server-side (400), so none are exposed here.
``background=True`` requires ``store=True``. Function calling is stateful-only
and MCP transport is Streamable HTTP with lowercase alphanumeric server names.

Create calls are NEVER auto-retried: a timed-out create may still execute (and
bill) server-side, so a retry could double-run the task.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from tools.registry import registry, tool_error
from tools.tool_backend_helpers import resolve_provider_secret
from tools.tool_output_truncate import truncate_head_tail

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_AGENT = "antigravity-preview-09-2026"
# Documented agent_config.model values (preview). Validated client-side so a
# typo fails fast instead of burning a billable run on a generic 400.
SUPPORTED_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_TIMEOUT_S = 600        # agentic runs take minutes; single blocking POST
MIN_TIMEOUT_S = 30
DEFAULT_STATUS_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 50_000
MAX_SOURCES = 20
MAX_SOURCE_CHARS = 1_000_000   # per inline source content
MAX_MCP_SERVERS = 10
_ERROR_BODY_CHARS = 2_000

# Remote MCP server names are strictly lowercase alphanumeric server-side
# (uppercase triggers a generic 400).
_MCP_NAME_RE = re.compile(r"[a-z0-9]+")


def _load_antigravity_config() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        return load_config().get("antigravity", {}) or {}
    except Exception:
        return {}


def _config_str(key: str, default: str) -> str:
    value = str(_load_antigravity_config().get(key, "") or "").strip()
    return value or default


def _config_int(key: str, default: int, floor: int) -> int:
    try:
        return max(floor, int(_load_antigravity_config().get(key, default)))
    except Exception:
        return default


def resolve_antigravity_api_key() -> str:
    """API key for the Interactions API: ANTIGRAVITY_API_KEY, then the Google
    keys the Gemini provider already uses. Resolved through
    ``resolve_provider_secret`` so profile secret scoping and ``~/.hermes/.env``
    behave like every other tool key. Never raises."""
    for env_var in ("ANTIGRAVITY_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        key = str(resolve_provider_secret(env_var, "") or "").strip()
        if key:
            return key
    return ""


def check_antigravity_requirements() -> bool:
    """True when an Interactions-API key resolves for this profile."""
    return bool(resolve_antigravity_api_key())


def _client(timeout_s: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_s)


def _user_agent() -> str:
    try:
        import hermes_cli as _hermes_cli

        return f"hermes-agent/{str(_hermes_cli.__version__)}"
    except Exception:
        return "hermes-agent"


def _validate_sources(sources: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Normalized inline ``environment.sources``; raises ValueError on bad input."""
    if not sources:
        return []
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError(f"sources supports at most {MAX_SOURCES} inline files")
    cleaned: List[Dict[str, str]] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object with target/content")
        target = str(source.get("target", "") or "").strip()
        content = source.get("content", "")
        if not target.startswith("/"):
            raise ValueError(
                f"sources[{index}].target must be an absolute sandbox path like "
                f"'/workspace/data.csv' (got {target!r})")
        if not isinstance(content, str) or not content:
            raise ValueError(f"sources[{index}].content must be a non-empty string")
        if len(content) > MAX_SOURCE_CHARS:
            raise ValueError(
                f"sources[{index}].content exceeds {MAX_SOURCE_CHARS} characters — "
                "inline sources carry text the model already has; trim or split the task")
        cleaned.append({"type": "inline", "target": target, "content": content})
    return cleaned


def _validate_mcp_servers(mcp_servers: Optional[List[Dict[str, Any]]]) -> List[Dict[str, str]]:
    if not mcp_servers:
        return []
    if not isinstance(mcp_servers, list) or len(mcp_servers) > MAX_MCP_SERVERS:
        raise ValueError(f"mcp_servers supports at most {MAX_MCP_SERVERS} servers")
    cleaned: List[Dict[str, str]] = []
    seen: set[str] = set()
    for index, server in enumerate(mcp_servers):
        if not isinstance(server, dict):
            raise ValueError(f"mcp_servers[{index}] must be an object with name/url")
        name = str(server.get("name", "") or "").strip()
        url = str(server.get("url", "") or "").strip()
        if not _MCP_NAME_RE.fullmatch(name):
            raise ValueError(
                f"mcp_servers[{index}].name must be lowercase alphanumeric "
                f"(Antigravity rejects uppercase names with a generic 400; got {name!r})")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"mcp_servers[{index}].url must be an http(s) URL (got {url!r})")
        if url.startswith("http://") or "text/event-stream" in url:
            # SSE transport is unsupported server-side; plain http works but https is the norm.
            logger.debug("antigravity mcp server %s uses non-https url", name)
        if name in seen:
            raise ValueError(f"mcp_servers has duplicate name {name!r}")
        seen.add(name)
        cleaned.append({"type": "mcp_server", "name": name, "url": url})
    return cleaned


def _build_interaction_payload(
    task: str,
    *,
    agent_id: str,
    model: str,
    max_total_tokens: Optional[int],
    sources: List[Dict[str, str]],
    mcp_servers: List[Dict[str, str]],
    previous_interaction_id: str,
    environment_id: str,
    background: bool,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"agent": agent_id, "input": task}
    agent_config: Dict[str, Any] = {"type": "antigravity"}
    if model:
        agent_config["model"] = model
    if max_total_tokens is not None:
        agent_config["max_total_tokens"] = int(max_total_tokens)
    payload["agent_config"] = agent_config
    if environment_id:
        if sources:
            raise ValueError(
                "environment_id (continuation) and sources (new sandbox) are mutually "
                "exclusive — continue with the existing environment or start fresh")
        payload["environment"] = environment_id
    elif sources:
        payload["environment"] = {"type": "remote", "sources": sources}
    if mcp_servers:
        payload["tools"] = mcp_servers
    if previous_interaction_id:
        payload["previous_interaction_id"] = previous_interaction_id
    if background:
        # Server-side requirement: background execution only persists with store=True.
        payload["background"] = True
        payload["store"] = True
    return payload


def _extract_interaction(data: Any) -> Dict[str, Any]:
    """Defensive field extraction from an Interaction REST object."""
    if not isinstance(data, dict):
        return {}
    environment = data.get("environment")
    return {
        "interaction_id": str(data.get("id") or data.get("name") or ""),
        "status": str(data.get("status") or ""),
        "output_text": str(data.get("output_text") or ""),
        "environment_id": str(
            data.get("environment_id")
            or (environment if isinstance(environment, str) else "")
            or ""),
        "usage": data.get("usage") if isinstance(data.get("usage"), dict) else {},
        "error": str(data.get("error") or data.get("error_message") or ""),
    }


def _post_interaction(payload: Dict[str, Any], api_key: str, base_url: str, timeout_s: float) -> httpx.Response:
    with _client(timeout_s) as client:
        return client.post(
            f"{base_url.rstrip('/')}/interactions",
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json",
                     "User-Agent": _user_agent()},
            json=payload,
        )


def _get_interaction(interaction_id: str, api_key: str, base_url: str, timeout_s: float) -> httpx.Response:
    with _client(timeout_s) as client:
        return client.get(
            f"{base_url.rstrip('/')}/interactions/{interaction_id}",
            headers={"x-goog-api-key": api_key, "User-Agent": _user_agent()},
        )


def antigravity_agent(
    task: str,
    model: str = "",
    max_total_tokens: Optional[int] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    mcp_servers: Optional[List[Dict[str, Any]]] = None,
    previous_interaction_id: str = "",
    environment_id: str = "",
    background: bool = False,
) -> str:
    """Run one task on the managed Antigravity agent and return its report JSON."""
    api_key = resolve_antigravity_api_key()
    if not api_key:
        return tool_error(
            "Antigravity agent tool requires a Gemini API key. Set ANTIGRAVITY_API_KEY "
            "(or GEMINI_API_KEY / GOOGLE_API_KEY) in ~/.hermes/.env — get one at "
            "https://aistudio.google.com/apikey")
    task = str(task or "").strip()
    if not task and not previous_interaction_id:
        return tool_error("task must not be empty")
    if not previous_interaction_id and not task:
        return tool_error("task is required unless previous_interaction_id continues a run")

    model = str(model or "").strip() or _config_str("model", DEFAULT_MODEL)
    if model not in SUPPORTED_MODELS:
        return tool_error(
            f"Unsupported model {model!r} — antigravity-preview-09-2026 accepts: "
            + ", ".join(SUPPORTED_MODELS))
    agent_id = _config_str("agent", DEFAULT_AGENT)
    base_url = _config_str("base_url", DEFAULT_BASE_URL)
    timeout_s = _config_int("timeout_s", DEFAULT_TIMEOUT_S, MIN_TIMEOUT_S)

    try:
        validated_sources = _validate_sources(sources)
        validated_mcp = _validate_mcp_servers(mcp_servers)
        if max_total_tokens is not None:
            max_total_tokens = int(max_total_tokens)
            if max_total_tokens <= 0:
                raise ValueError("max_total_tokens must be a positive integer")
        payload = _build_interaction_payload(
            task, agent_id=agent_id, model=model, max_total_tokens=max_total_tokens,
            sources=validated_sources, mcp_servers=validated_mcp,
            previous_interaction_id=str(previous_interaction_id or "").strip(),
            environment_id=str(environment_id or "").strip(),
            background=bool(background),
        )
    except (TypeError, ValueError) as exc:
        return tool_error(str(exc))

    try:
        response = _post_interaction(payload, api_key, base_url, timeout_s)
    except httpx.TimeoutException:
        return tool_error(
            f"Antigravity agent run exceeded the {timeout_s}s client timeout. The remote run "
            "may still be executing (and billing) — retry with background=true and poll "
            "antigravity_status, or raise antigravity.timeout_s in config.yaml")
    except httpx.HTTPError as exc:
        return tool_error(f"Antigravity agent request failed: {exc}")

    if response.status_code >= 400:
        return tool_error(
            f"Antigravity agent API returned HTTP {response.status_code}: "
            f"{response.text[:_ERROR_BODY_CHARS]}")

    interaction = _extract_interaction(response.json())
    status = interaction["status"]
    output = truncate_head_tail(interaction["output_text"], MAX_OUTPUT_CHARS)
    result: Dict[str, Any] = {
        "success": status in ("completed", "incomplete", "in_progress"),
        "status": status,
        "output_text": output,
        "interaction_id": interaction["interaction_id"],
        "environment_id": interaction["environment_id"],
        "usage": interaction["usage"],
        "agent": agent_id,
        "model": model,
    }
    if interaction["error"]:
        result["remote_error"] = interaction["error"]
    if status == "failed":
        result["success"] = False
    if status == "incomplete":
        result["hint"] = (
            "Token budget hit before completion. Continue with antigravity_agent("
            "task='continue', previous_interaction_id=<interaction_id>, "
            "environment_id=<environment_id>) — the continuation gets a fresh budget")
    if status == "in_progress":
        result["hint"] = (
            "Run is executing in the background — poll antigravity_status with "
            "interaction_id")
    return json.dumps(result, ensure_ascii=False)


def antigravity_status(interaction_id: str) -> str:
    """Fetch one Antigravity interaction (status + report) by id."""
    api_key = resolve_antigravity_api_key()
    if not api_key:
        return tool_error(
            "Antigravity agent tool requires a Gemini API key. Set ANTIGRAVITY_API_KEY "
            "(or GEMINI_API_KEY / GOOGLE_API_KEY) in ~/.hermes/.env")
    interaction_id = str(interaction_id or "").strip()
    if not interaction_id:
        return tool_error("interaction_id must not be empty")
    base_url = _config_str("base_url", DEFAULT_BASE_URL)
    status_timeout_s = _config_int("status_timeout_s", DEFAULT_STATUS_TIMEOUT_S, MIN_TIMEOUT_S)
    try:
        response = _get_interaction(interaction_id, api_key, base_url, status_timeout_s)
    except httpx.TimeoutException:
        return tool_error(f"antigravity_status timed out after {status_timeout_s}s")
    except httpx.HTTPError as exc:
        return tool_error(f"Antigravity status request failed: {exc}")
    if response.status_code >= 400:
        return tool_error(
            f"Antigravity agent API returned HTTP {response.status_code}: "
            f"{response.text[:_ERROR_BODY_CHARS]}")
    interaction = _extract_interaction(response.json())
    return json.dumps({
        "success": interaction["status"] != "failed",
        "status": interaction["status"],
        "output_text": truncate_head_tail(interaction["output_text"], MAX_OUTPUT_CHARS),
        "interaction_id": interaction["interaction_id"] or interaction_id,
        "environment_id": interaction["environment_id"],
        "usage": interaction["usage"],
    }, ensure_ascii=False)


# --- Registry wiring -------------------------------------------------------------

_ANTIGRAVITY_AGENT_SCHEMA = {
    "name": "antigravity_agent",
    "description": (
        "Delegate a whole task to Google's managed Antigravity agent (Antigravity 2.0's "
        "agent harness, preview): it reasons, runs shell commands and code, manages files, "
        "and browses the web inside Google's hosted Linux sandbox, then returns a final "
        "report. Runs typically take 1-10 minutes and consume Gemini API tokens per task "
        "(roughly $0.25-$5 depending on complexity). Use for self-contained research, "
        "data-crunching, or sandboxed build/analysis tasks — not for quick lookups. The "
        "remote agent has its OWN tools; it cannot touch this machine beyond the inline "
        "text sources you pass."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Complete, self-contained task instruction for the agent.",
            },
            "model": {
                "type": "string",
                "enum": list(SUPPORTED_MODELS),
                "description": "Underlying Gemini model (default gemini-3.8-flash).",
            },
            "max_total_tokens": {
                "type": "integer",
                "description": (
                    "Optional token budget for the whole run; the run stops early with "
                    "status 'incomplete' when exceeded (continue it to resume)."
                ),
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string",
                                   "description": "Absolute sandbox path, e.g. /workspace/data.csv."},
                        "content": {"type": "string", "description": "Inline text file content."},
                    },
                    "required": ["target", "content"],
                },
                "description": (
                    "Optional text files to mount into the sandbox (max 20, ~1M chars each) "
                    "so the agent can analyze data you already have."
                ),
            },
            "mcp_servers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string",
                                 "description": "Lowercase alphanumeric server name."},
                        "url": {"type": "string",
                                "description": "Streamable-HTTP MCP server URL."},
                    },
                    "required": ["name", "url"],
                },
                "description": "Optional remote MCP servers the agent may call (max 10).",
            },
            "previous_interaction_id": {
                "type": "string",
                "description": "Continue a prior interaction (stateful multi-turn or an "
                               "'incomplete' budget run).",
            },
            "environment_id": {
                "type": "string",
                "description": "Reuse the sandbox from a prior interaction (required when "
                               "continuing an 'incomplete' run).",
            },
            "background": {
                "type": "boolean",
                "description": (
                    "Start the run and return immediately with its interaction_id for "
                    "antigravity_status polling, instead of blocking until the report."
                ),
                "default": False,
            },
        },
        "required": ["task"],
    },
}

_ANTIGRAVITY_STATUS_SCHEMA = {
    "name": "antigravity_status",
    "description": (
        "Fetch the status and final report of an Antigravity agent interaction "
        "(poll after antigravity_agent ran with background=true)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "interaction_id": {
                "type": "string",
                "description": "Interaction id returned by antigravity_agent.",
            },
        },
        "required": ["interaction_id"],
    },
}


def _handle_antigravity_agent(args, **kw):
    return antigravity_agent(
        args.get("task", ""),
        model=args.get("model") or "",
        max_total_tokens=args.get("max_total_tokens"),
        sources=args.get("sources"),
        mcp_servers=args.get("mcp_servers"),
        previous_interaction_id=args.get("previous_interaction_id", ""),
        environment_id=args.get("environment_id", ""),
        background=bool(args.get("background", False)),
    )


def _handle_antigravity_status(args, **kw):
    return antigravity_status(args.get("interaction_id", ""))


registry.register(
    name="antigravity_agent", toolset="delegation", schema=_ANTIGRAVITY_AGENT_SCHEMA,
    handler=_handle_antigravity_agent, check_fn=check_antigravity_requirements,
    requires_env=["GEMINI_API_KEY"], emoji="🛸", max_result_size_chars=60_000,
)
registry.register(
    name="antigravity_status", toolset="delegation", schema=_ANTIGRAVITY_STATUS_SCHEMA,
    handler=_handle_antigravity_status, check_fn=check_antigravity_requirements,
    requires_env=["GEMINI_API_KEY"], emoji="🛰️", max_result_size_chars=60_000,
)
