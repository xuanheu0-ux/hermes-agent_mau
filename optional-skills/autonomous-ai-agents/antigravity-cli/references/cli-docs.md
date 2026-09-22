# Antigravity CLI docs, condensed (Antigravity 2.x / agy)

Source pages reviewed (2.x docs structure):
- `/docs/getting-started` (Antigravity CLI tab)
- `/docs/cli/using`
- `/docs/cli/features`
- `/docs/cli/reference`
- `/docs/cli/headless`
- `/docs/cli/conversations`
- `/docs/cli/troubleshooting`
- `/docs/remote-control` (Antigravity CLI tab)
- `/docs/models`
- `/changelog`

## Background

- Antigravity 2.0 launched at I/O 2026 (May 19, 2026) as five shapes of one
  agent runtime: desktop app, `agy` CLI, SDK, Managed Agents API, enterprise.
- The Go-based `agy` CLI replaced the Gemini CLI for Google AI Pro/Ultra on
  June 18, 2026 (Gemini Code Assist IDE extensions likewise). Enterprise and
  paid-API-key access were unaffected. Migration guide:
  `antigravity.google/docs/cli/gcli-migration`.
- Unlike the old open-source Gemini CLI, `agy` is closed source and does not
  speak ACP.

## Install

- macOS/Linux: `curl -fsSL https://antigravity.google/cli/install.sh | bash`
- Windows PowerShell: `irm https://antigravity.google/cli/install.ps1 | iex`
- Windows CMD: `curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd`
- Default binary location: `~/.local/bin/agy` (macOS/Linux),
  `C:\Users\<user>\AppData\Local\agy\bin` (Windows).
- Native self-updater runs in the background with a 15-min TTL debounce;
  state under `~/.gemini/antigravity-cli/updater/` (`update.lock`,
  `last_check.timestamp`). Disable with `AGY_CLI_DISABLE_AUTO_UPDATE=true`.

## Authentication

- Tries the OS secure keyring first (Apple Keychain / secret-service via D-Bus
  / Windows Credential Manager); refreshed OAuth tokens auto-save to the
  keyring (2.2.1+).
- If no saved session exists, falls back to browser-based Google sign-in.
- Local machine: opens the default browser. SSH/remote: prints a secure
  authorization URL, then expects the auth code to be pasted back.
- Headless runs use cached credentials only; with no TTY and no cached session
  they exit with an `authentication required` error (no hang).
- `/logout` removes saved credentials.
- Keyring errors over SSH/headless: unlock keyring / start a D-Bus session
  (`export $(dbus-launch)` on Linux; `security unlock-keychain` on macOS).

## Config and files

- App dir: `~/.gemini/antigravity-cli/`
- Settings: `~/.gemini/antigravity-cli/settings.json`
- Keybindings: `~/.gemini/antigravity-cli/keybindings.json`
- Plugins: `~/.gemini/antigravity-cli/plugins/<plugin_name>/` (+
  `import_manifest.json`)
- Logs: `~/.gemini/antigravity-cli/log/cli-*.log`
- Conversations: `~/.gemini/antigravity-cli/conversations/` — SQLite (`.db`)
  is the CLI's conversation format since 2.x; older JSONL files may remain on
  upgraded installs.
- Updater: `~/.gemini/antigravity-cli/updater/`

## Headless / print mode (`-p`)

- `agy -p "prompt"` (aliases `--print`, `--prompt`) runs once and exits.
  Response → stdout; diagnostics → stderr. Safe in scripts/subprocesses: with
  a flag prompt, stdin is not read (1.x hang fixed).
- `--output-format text|json|stream-json`:
  - `json`: one envelope — `conversation_id`, `status`, `response`, `error`,
    `duration_seconds`, `num_turns`, `usage{input_tokens,output_tokens,
    thinking_tokens,cache_read_tokens,total_tokens}`, plus
    `structured_output`/`json_schema` with `--json-schema`.
  - `stream-json`: NDJSON `init` → `step_update`* → `result` events; tool
    steps carry `tool_info` (name/parameters/output/error); subagent steps
    carry `subagent_info`.
- `--input-format stream-json` (requires `--output-format stream-json`):
  multi-turn single-process session; send
  `{"event":"user","message":{"content":"..."}}` lines on stdin, one `result`
  per turn; close stdin to end (exit 0). CLI-internal slash commands
  (`/model`, `/usage`) are unavailable in-stream.
- `--json-schema` accepts a schema string, a `.json` file path, or a primitive
  type name; parsed value lands in `structured_output`.
- Model selection: slugs from `agy models` (e.g. `gemini-3.8-flash-high`,
  `gemini-3.1-pro-high`, `claude-opus-4-6`); `--effort low|medium|high`;
  `--agent <name>` (list: `agy agents`). Unknown model ⇒ non-zero exit +
  `ERROR` envelope, no silent fallback.
- Resume: `--continue`/`-c` (most recent) or `--conversation <id>`; resumes are
  scoped to the launch directory.
- Permissions: unapproved tools are soft-denied (run continues, exit 0, stderr
  notice). Grant via `permissions.allow` rules or bypass with
  `--dangerously-skip-permissions` (also switches `permission_mode` to
  `always-proceed` in the `init` event).
- Timeout: `--print-timeout`, default `5m`. No `--max-turns` flag.
- Exit codes: `0` success; `1` error; `2` control-event/CLI-slash-command in
  stream mode; `3` agent/model API failure (structured `AGY_ERROR: {...}` JSON
  on stderr with status, retryability, error ID).
- Envelope `status` values: `SUCCESS`, `ERROR`, `CANCELED`, `INTERRUPTED`,
  `INVALID`, `WAITING`, `RUNNING`.

## Model lineup (per `/docs/models`, 2.15 era)

- Gemini 3.8 Flash / 3.7 Flash / 3.6 Flash (Low–High effort)
- Gemini 3.1 Pro (Low/High)
- Claude Sonnet 4.6 (Thinking), Claude Opus 4.6 (Thinking) — not on Enterprise
- GPT-OSS-120b — not on Enterprise
- Nano Banana 2 is used internally for generative image tasks.

## Useful slash commands (in-session)

- `/config`, `/settings`
- `/permissions`, `/model`, `/keybindings`, `/statusline`
- `/resume` / `/switch` / `/conversation`
- `/rewind` / `/undo`
- `/rename <name>`
- `/clear` / `/new`
- `/fork` / `/branch`
- `/add-dir <path>`, `/open <path>`
- `/tasks`, `/skills`, `/mcp`, `/hooks`, `/agents`
- `/context`, `/diff`, `/artifact`, `/copy`, `/fast`, `/planning`
- `/usage` / `/quota`, `/credits`, `/voice` / `/record`, `/title`
- `/boost <task>`, `/teamwork-preview <task>` (`/teamwork`, paid plans)
- `/btw <query>` (background side question)
- `/remote-control [on|off]`
- `/logout`, `/feedback`, `/help`

## Prompt helpers

- `@` path autocomplete
- `esc esc` clears prompt when not streaming
- `!` runs a terminal command
- `?` opens help / slash command list
- `ctrl+g` opens the prompt in `$EDITOR`; vim mode via `editorMode: "vim"`

## Keybindings (defaults, `keybindings.json`)

- Submit `enter`; newline `shift+enter`/`ctrl+j`/`alt+enter`
- Escape/cancel `ctrl+c`/`esc`; exit `ctrl+d` (empty prompt); clear screen
  `ctrl+l`; suspend `ctrl+z`
- Approve/deny `y`/`n`; edit proposed command `e`; external editor `ctrl+g`
- Review panel `ctrl+r`; toggle tool trajectory `ctrl+o`
- Subagent fast-path: teleport `alt+j`, fast-approve `ctrl+k`
- Paste `ctrl+v`; undo `ctrl+_`/`ctrl+shift+-`; redo `ctrl+shift+z`; yank
  `ctrl+y`
- Navigation `up`/`down`/`left`/`right`; page `pgup`/`pgdn` (or
  `shift+up`/`shift+down`); top/bottom `ctrl+home`/`ctrl+end`
- Dictation `F5`
- Malformed JSON in `keybindings.json` falls back to defaults for broken
  actions; set a list to `[]` to disable a binding.

## Permissions and sandbox

- Global preset key `toolPermission`: `request-review` (default),
  `proceed-in-sandbox`, `always-proceed`, `strict`.
- Fine-grained `permissions.allow`/`permissions.deny` with `action(target)`
  rules, e.g. `"command(git)"`, `"command(regex:npm run (build|lint|test))"`,
  `"write_file(src/)"`.
- Launch overrides: `--sandbox`, `--dangerously-skip-permissions` (settings
  panel shows the override indicator).
- Sandbox setting: `enableTerminalSandbox` in `settings.json` (default
  `false`); nsjail (Linux), sandbox-exec (macOS), AppContainer (Windows);
  Windows sandbox support landed in 2.15.1.

## Settings keys of note

`colorScheme`, `altScreenMode` (`default`/`always`/`never`), `toolPermission`,
`artifactReviewPolicy` (`asks-for-review`/`agent-decides`/`always-proceed`),
`notifications`, `showTips`, `showFeedbackSurvey`, `editor`, `editorMode`,
`vimInsertFirst`, `allowNonWorkspaceAccess`, `enableTerminalSandbox`,
`useG1Credits`, `enableTelemetry`, `verbosity` (`high`/`low`),
`runningLightSpeed`.

## Environment variables

`AGY_CLI_DISABLE_AUTO_UPDATE`, `AGY_CLI_HIDE_LOGO`,
`AGY_CLI_HIDE_ACCOUNT_INFO`, `AGY_CLI_CMD_OUTPUT_PERCENTAGE`,
`AGY_CLI_DISABLE_LATEX`, `AGY_CLI_DISABLE_ESCAPE_SEQUENCE_OPTIMIZATIONS`.

## Remote Control (2.x)

- Interactive: `/remote-control [on|off]` in a session, or launch with
  `--remote-control`. Tunnel exists only while that CLI process runs; prompts,
  tool approvals, and questions sync bidirectionally with the web UI
  (antigravity.google.com, same Google account).
- Headless daemon: `agy remote-control start|status|stop` registers with the
  OS service manager (`--name <label>`, `--session` to scope to login
  session); persists across logouts/reboots.

## Plugins

- Layout: `plugin.json` (required marker), optional `mcp_config.json`,
  `hooks.json`, `skills/`, `agents/`, `rules/`; staged under
  `~/.gemini/antigravity-cli/plugins/<plugin_name>/`, auto-discovered.
- Gemini CLI skills/hooks/subagents/extensions migrate as Antigravity plugins.

## Subagents

- `/agents` opens the Agent Manager Panel for active/completed subagents.
- Subagents run in parallel and surface approval requests via the Detail View
  or the Fast Path Alert above the prompt box.
- Headless: subagent steps appear as `step_update` events with
  `subagent_info`.
