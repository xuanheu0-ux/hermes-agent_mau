"""Tests for the Antigravity managed-agent delegation tool (tools/antigravity_tool.py).

HTTP is faked with httpx.MockTransport bound through the module's ``_client``
factory; the API key resolver is stubbed so no secret scope is needed.
"""

from __future__ import annotations

import json

import httpx
import pytest

import tools.antigravity_tool as agt


def _install(monkeypatch, handler, api_key="test-key"):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        agt, "_client",
        lambda timeout_s: httpx.Client(transport=transport, timeout=timeout_s))
    if api_key is not None:
        monkeypatch.setattr(agt, "resolve_antigravity_api_key", lambda: api_key)


def _completed(output="All done", interaction_id="ia-1", environment_id="env-1", usage=None):
    return {
        "id": interaction_id,
        "status": "completed",
        "output_text": output,
        "environment_id": environment_id,
        "usage": usage or {"total_tokens": 1234},
    }


def test_missing_key_is_a_clean_error(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("HTTP must not be called without a key"),
             api_key=None)
    result = json.loads(agt.antigravity_agent("do a thing"))
    assert result["error"].startswith("Antigravity agent tool requires a Gemini API key")


def test_success_payload_and_result(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_completed("Report body"))

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent(
        "Analyze /workspace/data.csv",
        model="gemini-3.6-flash",
        max_total_tokens=50_000,
        sources=[{"target": "/workspace/data.csv", "content": "id,val\n1,2\n"}],
        mcp_servers=[{"name": "weather", "url": "https://example.com/mcp"}],
    ))

    assert captured["url"].endswith("/v1beta/interactions")
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    payload = captured["payload"]
    assert payload["agent"] == agt.DEFAULT_AGENT
    assert payload["input"] == "Analyze /workspace/data.csv"
    assert payload["agent_config"] == {"type": "antigravity", "model": "gemini-3.6-flash",
                                       "max_total_tokens": 50000}
    assert payload["environment"] == {"type": "remote", "sources": [
        {"type": "inline", "target": "/workspace/data.csv", "content": "id,val\n1,2\n"}]}
    assert payload["tools"] == [{"type": "mcp_server", "name": "weather",
                                 "url": "https://example.com/mcp"}]

    assert result["success"] is True
    assert result["status"] == "completed"
    assert result["output_text"] == "Report body"
    assert result["interaction_id"] == "ia-1"
    assert result["environment_id"] == "env-1"
    assert result["usage"] == {"total_tokens": 1234}
    assert result["model"] == "gemini-3.6-flash"


def test_default_model_used_when_unset(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_completed())

    _install(monkeypatch, handler)
    agt.antigravity_agent("hello")
    assert captured["payload"]["agent_config"]["model"] == agt.DEFAULT_MODEL


def test_background_also_sets_store(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"id": "ia-9", "status": "in_progress",
                                         "output_text": "", "environment_id": "env-9"})

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("long task", background=True))
    assert captured["payload"]["background"] is True
    assert captured["payload"]["store"] is True
    assert result["interaction_id"] == "ia-9"


def test_in_progress_background_result_carries_poll_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "ia-9", "status": "in_progress",
                                         "output_text": "", "environment_id": "env-9"})

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("long task", background=True))
    assert result["success"] is True
    assert result["status"] == "in_progress"
    assert "antigravity_status" in result["hint"]


def test_incomplete_carries_continue_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "ia-2", "status": "incomplete",
                                         "output_text": "partial…", "environment_id": "env-2"})

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("big job"))
    assert result["success"] is True
    assert result["status"] == "incomplete"
    assert "previous_interaction_id" in result["hint"]


def test_continuation_params_forwarded(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_completed("finished the rest", "ia-2", "env-2"))

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent(
        "continue", previous_interaction_id="ia-2", environment_id="env-2"))
    assert captured["payload"]["previous_interaction_id"] == "ia-2"
    assert captured["payload"]["environment"] == "env-2"
    assert "sources" not in captured["payload"]
    assert result["output_text"] == "finished the rest"


def test_failed_status_is_failure_with_remote_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "ia-3", "status": "failed",
                                         "output_text": "", "error": "sandbox crashed"})

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("doomed task"))
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["remote_error"] == "sandbox crashed"


def test_unsupported_model_fails_before_http(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("must not reach HTTP"))
    result = json.loads(agt.antigravity_agent("hi", model="gemini-2.5-pro"))
    assert "Unsupported model" in result["error"]


def test_uppercase_mcp_name_rejected(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("must not reach HTTP"))
    result = json.loads(agt.antigravity_agent(
        "hi", mcp_servers=[{"name": "Weather", "url": "https://example.com/mcp"}]))
    assert "lowercase alphanumeric" in result["error"]


def test_sources_and_environment_id_are_mutually_exclusive(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("must not reach HTTP"))
    result = json.loads(agt.antigravity_agent(
        "hi", environment_id="env-2",
        sources=[{"target": "/workspace/x.txt", "content": "data"}]))
    assert "mutually exclusive" in result["error"]


def test_relative_source_target_rejected(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("must not reach HTTP"))
    result = json.loads(agt.antigravity_agent("hi", sources=[{"target": "data.csv",
                                                              "content": "x"}]))
    assert "absolute sandbox path" in result["error"]


def test_create_timeout_suggests_background(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("slow task"))
    assert "background=true" in result["error"]


def test_http_error_body_is_bounded(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="x" * 100_000)

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("hi"))
    assert "HTTP 429" in result["error"]
    assert len(result["error"]) < 3_000


def test_output_text_truncated(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completed("y" * (agt.MAX_OUTPUT_CHARS + 5_000)))

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_agent("hi"))
    assert len(result["output_text"]) <= agt.MAX_OUTPUT_CHARS + 200  # marker allowance


def test_status_tool_gets_interaction(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_completed("final report", "ia-7", "env-7"))

    _install(monkeypatch, handler)
    result = json.loads(agt.antigravity_status("ia-7"))
    assert captured["url"].endswith("/v1beta/interactions/ia-7")
    assert result["success"] is True
    assert result["output_text"] == "final report"
    assert result["status"] == "completed"


def test_status_empty_id_rejected(monkeypatch):
    _install(monkeypatch, lambda request: pytest.fail("must not reach HTTP"))
    result = json.loads(agt.antigravity_status("  "))
    assert "interaction_id" in result["error"]


def test_check_fn_follows_key_resolution(monkeypatch):
    monkeypatch.setattr(agt, "resolve_provider_secret",
                        lambda env_var, provider_id, config_value="": 
                        "k" if env_var == "GEMINI_API_KEY" else "")
    assert agt.check_antigravity_requirements() is True
    monkeypatch.setattr(agt, "resolve_provider_secret",
                        lambda env_var, provider_id, config_value="": "")
    assert agt.check_antigravity_requirements() is False


def test_tools_registered():
    from tools.registry import registry
    # Discovery imports tools/antigravity_tool.py for its registration side effect;
    # a direct import here already ran registry.register() at module top level.
    assert "antigravity_agent" in registry._tools
    assert "antigravity_status" in registry._tools
    assert registry._tools["antigravity_agent"].toolset == "delegation"
    assert registry._tools["antigravity_status"].toolset == "delegation"
