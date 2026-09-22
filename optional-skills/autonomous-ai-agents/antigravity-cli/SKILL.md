---
name: antigravity-cli
description: "Operate the Antigravity CLI (agy 2.x): headless runs, auth, plugins, sandbox."
version: 0.3.0
author: Tony Simons (asimons81), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Coding-Agent, Antigravity, CLI, Auth, Plugins, Sandbox, Headless]
    related_skills: [grok, codex, claude-code, hermes-agent]
---

# Antigravity CLI (`agy`)

Operator guide for the Antigravity CLI, invoked as `agy`. Run all `agy`
commands through the Hermes `terminal` tool; inspect its config and logs with
`read_file`. This skill is reference + procedure — it does not wrap a network
API, so there is nothing to authenticate from Hermes itself.

**Targets the Antigravity 2.x CLI** (the Go `agy` shipped with Antigravity 2.0
at I/O 2026). Since 2026-06-18 the legacy Gemini CLI no longer serves Google AI
Pro/Ultra requests — `agy` is the supported replacement, so this skill assumes
2.x behavior (JSON headless output, model slugs, remote control) and no longer
matches the old 1.x CLI.

## When to Use

- Installing, updating, or smoke-testing the `agy` binary
- Driving non-interactive `agy --print` / `agy -p` one-shots (plain text,
  `--output-format json`, or `stream-json`)
- Debugging Antigravity auth, sandbox, permissions, or plugin state
- Reading Antigravity settings, keybindings, conversations, or logs

## Mental model

Antigravity has two layers — keep them distinct or the guidance will be wrong:

1. **Shell wrapper commands** — `agy help`, `agy install`, `agy plugin`,
   `agy models`, `agy agents`, `agy remote-control`, `agy update`,
   `agy changelog`. Run these through the `terminal` tool.
2. **Interactive in-session slash commands** — `/config`, `/permissions`,
   `/skills`, `/agents`, `/remote-control`, etc. These only exist inside a
   running `agy` TUI session, not on the shell wrapper.

`agy help` shows the shell wrapper surface, NOT the in-session slash commands.

## Prerequisites

- The `agy` binary on PATH. Default install location is `~/.local/bin/agy`
  (Windows: `%LOCALAPPDATA%\agy\bin`). Verify through the `terminal` tool:
  `command -v agy && agy --version`.
- No env vars or API keys required by this skill — Antigravity manages its own
  auth via the OS keyring / browser sign-in (see Authentication below).

## How to Run

Invoke every `agy` command through the `terminal` tool. Examples:

```
terminal(command="agy --version")
terminal(command="agy help")
terminal(command="agy plugin list")
terminal(command="agy --print 'Summarize the repo in 3 bullets'", workdir="/path/to/project")
```

For an interactive multi-turn TUI session, launch `agy` with `pty=true` (and
tmux for capture/monitoring), the same pattern the `codex` / `claude-code`
skills use. For one-shot smoke tests and scripted prompts, prefer
`agy -p` (non-interactive).

To inspect Antigravity's own files, use `read_file` on the paths under Core
paths below — do not `cat` them through the terminal.

## Delegation patterns

`agy` is a coding-agent backend in the same family as `codex` / `claude-code`,
so the same delegation shapes apply. Use these when handing real work (features,
fixes, reviews, second opinions) to Antigravity rather than just smoke-testing.

### One-shot (preferred for scripted prompts and second opinions)

```
terminal(command="agy -p 'Review this diff for bugs and security issues' --model gemini-3.8-flash-high", workdir="/path/to/repo", timeout=300)
```

`-p` is non-interactive: it runs the prompt and exits. Pin the engine with
`--model` using a **slug** from `agy models` (e.g. `gemini-3.8-flash-high`,
`gemini-3.1-pro-high`, `claude-opus-4-6`); set reasoning effort with
`--effort low|medium|high`. An unknown `--model` fails loudly (non-zero exit,
`ERROR` status) — headless mode never silently falls back. Add extra context
roots with repeatable `--add-dir`, or `/add-dir <path>` in-session. Select a
custom agent with `--agent <name>` (list with `agy agents`).

For machine-readable results use `--output-format json`, which prints one
envelope with `conversation_id`, `status`, `response`, `error`,
`duration_seconds`, `num_turns`, and `usage` token counts:

```
terminal(command="agy -p 'Audit auth.py for injection risks' --output-format json --print-timeout 10m", workdir="/path/to/repo", timeout=700)
```

Parse `.response` / `.status` out of the envelope (pipe through `jq` in shell).
The `conversation_id` is what you pass to `--conversation <id>` to resume.

### Long / bounded runs (tests, builds, multi-file changes)

Background it and get notified on completion, the same as the `codex` skill:

```
terminal(command="agy -p 'Implement the change described in TASK.md and run the tests' --dangerously-skip-permissions", workdir="/path/to/repo", background=true, notify_on_complete=true)
# then: process(action="poll"/"log"/"wait", session_id=<id>)
```

A headless run waits up to **`--print-timeout`** (default `5m`) for a response.
Raise it for long tasks (`--print-timeout 20m`) and pair with the `terminal`
`timeout=` so the outer call doesn't cut the run short. There is **no
`--max-turns`** on `agy`.

Without `--dangerously-skip-permissions`, headless mode **soft-denies** tools
that would need interactive approval (the run still exits `0` and prints a
notice on stderr naming the tool). Grant specific tools ahead of time via
`permissions.allow` rules in `settings.json` (e.g. `"command(git)"`,
`"command(regex:npm run (build|lint|test))"`, `"write_file(src/)"`) instead of
skipping permissions wholesale.

### Multi-turn scripted sessions (single process)

Instead of repeated `-p --continue` invocations, hold one process open and feed
prompts on stdin — each prompt gets its own `result` event on stdout:

```
agy --input-format stream-json --output-format stream-json
# send: {"event":"user","message":{"content":"..."}}
# read: {"event":"result","result":{...}}   (one per turn)
```

Requires `--output-format stream-json`; do not pass `-p` alongside it (flag
prompts are dropped in this mode). Clean sessions exit `0` when stdin closes.
CLI-internal slash commands (`/model`, `/usage`, …) are unavailable in the
stream — run them as standalone `agy -p /model` calls.

### Interactive multi-turn (PTY + tmux)

For a conversational session, launch `agy -i` (or bare `agy`) under `pty=true`
with tmux for `capture-pane` / `send-keys`, exactly the pattern documented in
the `codex` / `claude-code` skills. Resume later with `--continue` / `-c` or a
specific `--conversation <id>`. Closing the CLI prints the exact resume
command for that session. Conversations are **scoped to the launch directory**
— resume from the same workspace or the session won't be listed.

### Parallel instances (batch sub-issue / worktree fan-out)

Create one git worktree per task and launch an independent `agy -p` in each
(background), then collect results — same worktree fan-out the `codex` skill
uses for batch issue fixing. Bound concurrency to what the machine and your
review capacity can absorb.

### Output formats and exit codes (2.x)

| `--output-format` | stdout shape | Use for |
| --- | --- | --- |
| `text` (default) | Response text only | Human-readable output, quick checks |
| `json` | One JSON envelope on completion | Capturing result + metadata |
| `stream-json` | NDJSON events (`init` → `step_update`… → `result`) | Monitoring tools/progress/tokens live |

- Diagnostics (errors, auth prompts, permission notices) go to **stderr**, so
  `answer=$(agy -p '...')` captures a clean response.
- Exit `0` = success. Non-zero = failed; reason on stderr, and in JSON modes
  also in the envelope's `status`/`error` fields. Status values: `SUCCESS`,
  `ERROR`, `CANCELED`, `INTERRUPTED`, `INVALID`, `WAITING`, `RUNNING`. An
  agent/model API failure mid-turn prints a structured `AGY_ERROR: {...}` JSON
  line on stderr (with retryability and error ID) and exits `3`.
- With `--json-schema '<schema-or-file>'` (JSON modes), the parsed object lands
  in the envelope's `structured_output` field.

### Orchestration boundary

Antigravity is a **worker execution backend or third-opinion reviewer** — an
execution detail owned by the agent/profile running a task, NOT a first-class
orchestration primitive. Do not put `agy` on a kanban board as its own card or
treat it as a coordination layer; route work through the normal task graph and
let the assigned worker choose `agy` (vs. codex/claude-code/direct tools) as its
method. Reach for it explicitly only when the user asks, when a worker is
configured to wrap it, or when you want a Gemini/Claude-family cross-check
against another agent's plan or diff.

## Core paths

- Binary / entrypoint: `agy` (default `~/.local/bin/agy`; Windows
  `%LOCALAPPDATA%\agy\bin`)
- App data dir: `~/.gemini/antigravity-cli/`
- Settings file: `~/.gemini/antigravity-cli/settings.json`
- Keybindings file: `~/.gemini/antigravity-cli/keybindings.json`
- Logs: `~/.gemini/antigravity-cli/log/cli-*.log`
- Conversations: `~/.gemini/antigravity-cli/conversations/` — SQLite (`.db`)
  is the current conversation store; older 1.x JSONL/`history.jsonl` files may
  still exist on upgraded installs
- Plugin staging: `~/.gemini/antigravity-cli/plugins/<plugin_name>/`
  (+ `import_manifest.json`)
- Self-updater state: `~/.gemini/antigravity-cli/updater/`
  (`update.lock`, `last_check.timestamp`)

## Quick Reference

### Wrapper commands
- `agy changelog`
- `agy help`
- `agy install`
- `agy models` (list model slugs)
- `agy agents` (list custom agents)
- `agy plugin` / `agy plugins`
- `agy remote-control start|status|stop` (headless daemon)
- `agy update`

### Useful flags
- `--add-dir`
- `--agent`
- `--conversation`
- `--continue` / `-c`
- `--dangerously-skip-permissions`
- `--effort low|medium|high`
- `--input-format stream-json`
- `--json-schema`
- `--log-file`
- `--model` (slug, see `agy models`)
- `--output-format text|json|stream-json`
- `--print` / `-p` / `--prompt`
- `--print-timeout` (default `5m`)
- `--prompt-interactive` / `-i`
- `--remote-control`
- `--sandbox`
- `--version`

### Plugin subcommands (`agy plugin --help`)
- `list`, `import [source]`, `install <target>`, `uninstall <name>`,
  `enable <name>`, `disable <name>`, `validate [path]`, `link <mp> <target>`,
  `help`

### Install flags (`agy install --help`)
- `--dir`, `--skip-aliases`, `--skip-path`

### In-session slash commands
- **Conversation control:** `/resume` (`/switch`, `/conversation`), `/rewind`
  (`/undo`), `/rename <name>`, `/clear` (`/new`), `/fork` (`/branch`),
  `/exit` (`/quit`)
- **Settings & tools:** `/config` (`/settings`), `/permissions`, `/model`,
  `/keybindings`, `/statusline`, `/tasks`, `/skills`, `/mcp`,
  `/add-dir <path>`, `/open <path>`, `/hooks`, `/context`, `/diff`,
  `/artifact`, `/title`, `/voice` (`/record`), `/usage` (`/quota`),
  `/credits`, `/logout`, `/agents`, `/fast`, `/planning`
- **Reasoning:** `/boost <task>`, `/teamwork-preview <task>` (`/teamwork`,
  paid plans)
- **Utilities:** `/btw <query>`, `/copy`, `/feedback`, `/help`,
  `/remote-control [on|off]`
- **Prompt helpers:** `@` path autocomplete, `esc esc` clears the prompt (when
  not streaming), `!` runs a terminal command directly, `?` opens help.
  Vim-style prompt editing is available via `editorMode: "vim"`.

## Settings and permissions

### Common settings keys (`settings.json`)
- `toolPermission` — global preset: `request-review` (default),
  `proceed-in-sandbox`, `always-proceed`, `strict`
- `permissions.allow` / `permissions.deny` — fine-grained rules with
  `action(target)` syntax, e.g. `"command(git)"`,
  `"command(regex:npm run (build|lint|test))"`, `"write_file(src/)"`
- `allowNonWorkspaceAccess` — let file tools leave recognized Git/workspace
  roots (default `false`)
- `artifactReviewPolicy` — `asks-for-review` (default), `agent-decides`,
  `always-proceed`
- `enableTerminalSandbox` — boolean, default `false`
- `altScreenMode` — `default` | `always` | `never`
- `verbosity` — `high` (default) | `low` (quieter tool-call output)
- `editor` / `editorMode` / `vimInsertFirst` — external editor and vim-mode
  prompt editing
- `colorScheme`, `notifications`, `showTips`, `enableTelemetry`,
  `useG1Credits`

### Permission modes
`request-review`, `always-proceed`, `strict`, `proceed-in-sandbox` (the
`/permissions` panel exposes the main three; `proceed-in-sandbox` is the
sandboxed auto-proceed preset).

### Sandbox behavior
- `enableTerminalSandbox` is a boolean in `settings.json`; default `false`.
  Backed by `nsjail` (Linux), `sandbox-exec` (macOS), `AppContainer` (Windows).
- Launch-time overrides (`--sandbox`, `--dangerously-skip-permissions`) can
  supersede persistent settings for the current session; the settings panel
  shows an override indicator.

## Remote Control (2.x)

Drive a running CLI from a browser via the Antigravity web UI:

- In-session: `/remote-control` (or `--remote-control` at launch). The tunnel
  lives only as long as that CLI process; tool approvals can be answered from
  either side.
- Headless daemon: `agy remote-control start` registers an always-on instance
  with the OS service manager (`--name` for a label, `--session` to scope to
  the login session); check with `status`, remove with `stop`.

## Environment variables

- `AGY_CLI_DISABLE_AUTO_UPDATE=true` — disable the background self-updater
- `AGY_CLI_HIDE_LOGO=true` — suppress banner art (narrow terminals, recordings)
- `AGY_CLI_HIDE_ACCOUNT_INFO=true` — hide email/plan from the header
- `AGY_CLI_CMD_OUTPUT_PERCENTAGE=<n>` — max command-output height as % of
  terminal height
- `AGY_CLI_DISABLE_LATEX=true` — turn off LaTeX rendering
- `AGY_CLI_DISABLE_ESCAPE_SEQUENCE_OPTIMIZATIONS=true` — bypass renderer
  dirty-rectangle optimizations (screen readers / fragile terminals)

## Authentication behavior

- The CLI tries the OS secure keyring first (Apple Keychain, secret-service via
  D-Bus, Windows Credential Manager); refreshed OAuth tokens auto-save there.
- With no saved session, it falls back to browser-based Google sign-in.
- Locally it opens the default browser; over SSH it prints an authorization URL
  and expects the auth code pasted back.
- Headless runs use cached credentials only. In CI (no TTY) an unauthenticated
  run exits with an `authentication required` error instead of hanging —
  authenticate once interactively first.
- Keyring trouble over SSH/headless: unlock the keyring (macOS:
  `security unlock-keychain ...`; Linux: ensure a D-Bus session, e.g.
  `export $(dbus-launch)`).
- `/logout` removes saved credentials.

## Plugins

- Plugins stage under `~/.gemini/antigravity-cli/plugins/<plugin_name>/` and
  can bundle `skills/`, `agents/`, `rules/`, MCP servers (`mcp_config.json`),
  and hooks (`hooks.json`); a `plugin.json` marker is required.
- `agy plugin list` returning no imported plugins is a valid empty state.
- Gemini CLI customizations (skills, hooks, subagents, extensions) migrate over
  as Antigravity plugins — see `antigravity.google/docs/cli/gcli-migration`.

## Pitfalls

- `agy help` shows wrapper commands, not interactive slash commands.
- `agy --version` is the safe non-interactive version check; `agy version` is
  interactive and can fail without a real TTY.
- First place to look for failures: `~/.gemini/antigravity-cli/log/cli-*.log`
  (read with `read_file`).
- Don't confuse persistent JSON settings with launch-time overrides.
- On WSL, token storage is file-based, so auth issues are usually local-file /
  session-state problems, not browser-only problems.
- Conversations and resumes are **scoped to the launch directory** — run from
  the same workspace or `--continue` won't find the thread.
- `agy -p` is safe to run from scripts and subprocesses: with a prompt passed
  via flag it does not read stdin (the old 1.x hang is fixed). In
  `--input-format stream-json` mode, though, prompts on the flag are dropped —
  feed stdin instead.
- 2.x headless **does** support machine-readable output: use
  `--output-format json` / `stream-json` (optionally `--json-schema`) instead
  of scraping plain text. Still no `--max-turns`; bound runs with
  `--print-timeout` (default `5m`).
- Headless permission handling is **soft-deny**: unapproved tools don't crash
  the run (exit stays `0`, notice on stderr). If an `agy -p` run "did nothing",
  check stderr for the soft-deny notice and add `permissions.allow` rules.
- An unknown `--model` fails the run (non-zero, `ERROR` envelope) — parse
  slugs from `agy models` rather than guessing display strings.
- `~/.gemini/antigravity-cli/bin/agentapi` is a thin wrapper to `agy agentapi`.
- If updates stall: `rm -f ~/.gemini/antigravity-cli/updater/update.lock` or
  set `AGY_CLI_DISABLE_AUTO_UPDATE=true`.

## Verification

Confirm the install is real and usable, all through the `terminal` tool (read
files with `read_file`):

1. `terminal(command="command -v agy")`
2. `terminal(command="agy --version")`
3. `terminal(command="agy help")`
4. `terminal(command="agy models")`
5. `terminal(command="agy plugin list")`
6. `read_file` on `~/.gemini/antigravity-cli/settings.json`
7. `read_file` on the latest `~/.gemini/antigravity-cli/log/cli-*.log`
8. If needed, `read_file` on `~/.gemini/antigravity-cli/keybindings.json`

## Support files

- `references/cli-docs.md` — condensed notes from the Antigravity 2.x getting
  started, using, features, reference, and headless docs.
