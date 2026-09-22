---
sidebar_position: 5
title: "Antigravity Integration"
description: "Run Hermes Agent inside Google Antigravity 2.0 — as an MCP tool server, side-by-side in a terminal, or via skills reuse"
---

# Antigravity Integration

[Google Antigravity 2.0](https://antigravity.google) is Google's agent-first development platform (desktop app, `agy` CLI, and IDE). Hermes integrates with it four ways — pick by what you want Hermes to do there:

| | ① MCP tool server (recommended) | ② Terminal side-by-side | ③ ACP editor session | ④ Task provider (managed agent) |
|---|---|---|---|---|
| **What it is** | Antigravity's agent calls Hermes' messaging-bridge tools over MCP | Run the `hermes` TUI in a terminal next to (or inside) Antigravity | Antigravity drives Hermes as an ACP agent backend | Hermes hands whole tasks to Google's managed Antigravity agent (Gemini API) |
| **Hermes runs** | Spawned by Antigravity as a stdio MCP process | Wherever you launch it | Spawned by an ACP-compatible editor | Anywhere; the task runs in Google's hosted sandbox |
| **Best for** | Letting the Antigravity agent read/send your messages and manage Hermes approvals | Full Hermes (memory, skills, cron, gateway) while you work in Antigravity | Other editors — **not Antigravity 2.x** (see below) | Research / data / sandboxed build tasks that can run 1–10 min unattended |
| **Setup** | One JSON block (below) | None — `hermes` on PATH | `hermes acp` (Zed/VS Code/JetBrains/Buzz only) | `GEMINI_API_KEY` + the `delegation` toolset |

:::note Why no ACP path for Antigravity?
Hermes' [ACP adapter](../user-guide/features/acp.md) works with ACP-compatible editors (Zed, VS Code, JetBrains, Buzz). Antigravity's 2.x CLI (`agy`) is closed-source and [dropped ACP support](https://antigravity.google/docs/cli/gcli-migration) when it replaced the Gemini CLI (which was open-source and spoke ACP). Use the MCP path instead — it is supported across all three Antigravity surfaces (2.0 desktop, CLI, IDE).
:::

## ① Hermes as an MCP server inside Antigravity (recommended)

Hermes ships a stdio MCP server (`hermes mcp serve`) that exposes your messaging conversations as tools. Once wired in, the Antigravity agent can list conversations, read history, send messages on your connected platforms (Telegram, Discord, Slack, WhatsApp, Signal, Matrix, …), and respond to Hermes approval requests — all from inside Antigravity.

This integration is verified against the [Antigravity MCP configuration format](https://antigravity.google/docs/mcp) (`{"mcpServers": {...}}`) and smoke-tested end-to-end: MCP initialize → `tools/list` (10 tools) → `channels_list` call against `hermes mcp serve`.

### Prerequisites

- Hermes installed the normal way (`hermes` on PATH) — see the [Quick Install](https://hermes-agent.nousresearch.com/docs/) guide.
- For MCP you don't need a model provider configured in Hermes; the bridge tools work against your gateway state (empty state returns empty results, as any MCP client sees them).

### Antigravity CLI (`agy`)

Edit the global config at `~/.gemini/config/mcp_config.json` (all users, all workspaces) or drop a `.agents/mcp_config.json` in a specific project:

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then run `agy` in any workspace and type `/mcp` — the **MCP Manager overlay** shows a live status ring for the `hermes` server. Antigravity launches `hermes mcp serve` on demand over stdio.

### Antigravity 2.0 desktop

1. Open **Settings** (bottom left) → **Customizations** → **Installed MCP Servers**.
2. Click **Add MCP** to browse the MCP Store, or edit the raw config — the same `~/.gemini/config/mcp_config.json` format as above.

### Antigravity IDE

1. Click **…** at the top of the agent side panel → **MCP Servers** → **Manage MCP Servers** → **View raw config**.
2. Add the same `hermes` block to `~/.gemini/config/mcp_config.json` (global) or `.agents/mcp_config.json` (workspace).

### Variants

**Running from a dev checkout** (no installed `hermes` launcher) — point `command` at the checkout's entry point and pin `cwd`:

```json
{
  "mcpServers": {
    "hermes": {
      "command": "/path/to/hermes-agent/.venv/bin/hermes",
      "args": ["mcp", "serve"],
      "cwd": "/path/to/hermes-agent"
    }
  }
}
```

**Read-only bridge** — withhold the action tools so Antigravity can read but never send or approve:

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"],
      "disabledTools": ["messages_send", "permissions_respond"]
    }
  }
}
```

**Custom Hermes home / profile** — pass env through the server entry:

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"],
      "env": { "HERMES_HOME": "/home/you/.hermes-work" }
    }
  }
}
```

### Tools exposed to the Antigravity agent

| Tool | Purpose |
|------|---------|
| `conversations_list` | List active messaging conversations across connected platforms |
| `conversation_get` | Get detailed info about one conversation by session key |
| `messages_read` | Read recent messages from a conversation |
| `attachments_fetch` | List non-text attachments for a message |
| `events_poll` | Poll for new conversation events since a cursor |
| `events_wait` | Long-poll for the next conversation event |
| `messages_send` | Send a message to a platform conversation |
| `channels_list` | List available messaging channels and targets |
| `permissions_list_open` | List pending Hermes approval requests |
| `permissions_respond` | Respond to a pending approval request |

### Verify it works

1. Smoke-test the server standalone: `hermes mcp serve` starts silently on stdio (Ctrl+C to exit; add `-v` for debug logging on stderr).
2. In `agy`: `/mcp` shows the `hermes` status ring as active.
3. Ask the Antigravity agent: *"Use the hermes server to list my channels"* — you should get the JSON `channels_list` payload back.

### Security

`messages_send` and `permissions_respond` let the Antigravity agent act **as you** across your messaging platforms and rule on Hermes permission requests. Anything you allow the Antigravity agent to do, it can request through these tools — prefer the `disabledTools` read-only variant unless you trust the workspace, and keep your Hermes gateway owner-only.

## ② Terminal side-by-side

Nothing stops you from running full Hermes next to Antigravity — same machine, same repo, both surfaces visible:

```bash
hermes        # TUI in any terminal
```

Antigravity 2.0's desktop app has an integrated sidebar terminal on Enterprise/Business plans (since 2.14.0); on other plans, run `hermes` in a regular terminal window alongside the app. This gives you Hermes' complete feature set (memory, skills, cron, gateway, subagents) with copy-paste proximity to Antigravity's agent — e.g. hand a diff from one to the other.

## ③ Skills reuse

Both Hermes and Antigravity implement the [agentskills.io](https://agentskills.io) open skill standard, so Hermes skills (see the [skills catalog](../reference/optional-skills-catalog.md)) can be loaded by Antigravity's `/skills` surface as well — and vice versa. When driving the `agy` CLI *from* Hermes, see the **[antigravity-cli skill](../user-guide/skills/optional/autonomous-ai-agents/autonomous-ai-agents-antigravity-cli.md)**.

## ④ Antigravity as a task provider (managed agent)

The reverse of ①: instead of Antigravity calling Hermes, **Hermes delegates whole tasks to Google's managed Antigravity agent** — the same harness as the Antigravity 2.0 IDE, exposed as [`antigravity-preview-09-2026`](https://ai.google.dev/gemini-api/docs/antigravity-agent) on the Gemini API's Interactions API. The remote agent reasons, runs shell commands and code, manages files, and browses the web **inside Google's hosted Linux sandbox**, then returns a final report to Hermes.

:::note Delegation, not model swap
This is task-level delegation, not a drop-in LLM provider — Hermes' agent loop and tools stay local; the remote agent does the legwork in its own sandbox and reports back. To run the same *models* Antigravity uses (Gemini 3.8/3.7/3.6 Flash, 3.1 Pro) as Hermes' brain, configure the normal [Google provider](../guides/google-gemini.md) instead.
:::

### Setup

1. Put a Gemini API key in `~/.hermes/.env` (a dedicated `ANTIGRAVITY_API_KEY`, or reuse `GEMINI_API_KEY` / `GOOGLE_API_KEY`) — get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Enable the `delegation` toolset (`hermes tools` → delegation, or `tools.<platform>.enabled` in config.yaml). `antigravity_agent` and `antigravity_status` appear once the key resolves.

### Usage

The agent gets two tools:

- **`antigravity_agent(task, model?, max_total_tokens?, sources?, mcp_servers?, previous_interaction_id?, environment_id?, background?)`** — run one task and block until the report (runs typically take 1–10 minutes; default client timeout 600 s via `antigravity.timeout_s`). With `background=true` it returns immediately with an `interaction_id` for polling. `sources` mounts inline text files into the sandbox (`/workspace/...`), `mcp_servers` attaches remote Streamable-HTTP MCP servers (lowercase alphanumeric names).
- **`antigravity_status(interaction_id)`** — fetch status/report of a background run.

Model selection (`agent_config.model`, default `gemini-3.8-flash`): `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`. Config overrides in config.yaml:

```yaml
antigravity:
  agent: antigravity-preview-09-2026   # managed agent id
  model: gemini-3.8-flash
  timeout_s: 600                       # client-side cap for a blocking run
  # base_url: https://generativelanguage.googleapis.com/v1beta
```

A run that hits its token budget returns `status: incomplete` plus a hint — the tool continues it with `previous_interaction_id` + `environment_id` (the continuation gets a fresh budget). Failed runs surface the remote error verbatim. Create calls are never auto-retried (a timed-out run may still execute and bill server-side).

### Cost and limits

Preview API — pricing scales with task complexity (Google's estimates: **$0.25–$5+ per task**, 100k–5M tokens; sandbox compute is free during preview). The tool validates models, MCP names, and source sizes client-side so malformed calls fail before spending anything. Generation config (`temperature`, `top_p`, …) and structured output are rejected by the API and are not exposed.
