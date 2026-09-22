---
sidebar_position: 5
title: "Antigravity Integration"
description: "Run Hermes Agent inside Google Antigravity 2.0 — as an MCP tool server, side-by-side in a terminal, or via skills reuse"
---

# Antigravity Integration

[Google Antigravity 2.0](https://antigravity.google) is Google's agent-first development platform (desktop app, `agy` CLI, and IDE). Hermes integrates with it three ways — pick by what you want Hermes to do there:

| | ① MCP tool server (recommended) | ② Terminal side-by-side | ③ ACP editor session |
|---|---|---|---|
| **What it is** | Antigravity's agent calls Hermes' messaging-bridge tools over MCP | Run the `hermes` TUI in a terminal next to (or inside) Antigravity | Antigravity drives Hermes as an ACP agent backend |
| **Hermes runs** | Spawned by Antigravity as a stdio MCP process | Wherever you launch it | Spawned by an ACP-compatible editor |
| **Best for** | Letting the Antigravity agent read/send your messages and manage Hermes approvals | Full Hermes (memory, skills, cron, gateway) while you work in Antigravity | Other editors — **not Antigravity 2.x** (see below) |
| **Setup** | One JSON block (below) | None — `hermes` on PATH | `hermes acp` (Zed/VS Code/JetBrains/Buzz only) |

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
