# Reaching Claude

The robot can talk to Claude two ways. Pick one with `CLAUDE_BACKEND` in `.env`.

| | `cli`: Claude Code (`claude -p`) | `api`: Claude API |
|---|---|---|
| Account | Your Claude subscription | Claude Console, pay per use |
| Credential | `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` | `ANTHROPIC_API_KEY` |
| Cost | Part of the subscription; counts toward its usage limits, shared with your own Claude Code use | Per token (cents per day at normal use) |
| Speed | ~4–5 s per reaction (starts Claude Code each time) | ~2 s |
| Refusal fallback | – | Built in (`fallbacks="default"`) |

## cli (default)

The robot gets its own long-lived token. It's separate from your laptop's Claude Code
login, so neither can break the other, and you can revoke it on its own:

```sh
make claude-token     # on the host: opens a browser login, prints a long-lived token
# put it in .env:
#   CLAUDE_BACKEND=cli
#   CLAUDE_CODE_OAUTH_TOKEN=<token>
make ask TEXT="hello, can you hear me?"
```

How it's called (`robot/brain.py: _ask_claude_code`):

```
claude -p --output-format json --no-session-persistence
       --tools "" --strict-mcp-config --setting-sources ""
       --model $CLAUDE_MODEL --effort $CLAUDE_EFFORT
       --system-prompt <robot persona> --json-schema <{speak, text, language}>
       <scene description / transcript>
```

- `--tools ""` switches off every tool: this Claude can't read files or run commands, it
  only answers. MCP servers and settings files are ignored too, and it runs in an empty
  temporary directory.
- The reply comes back as structured JSON (`structured_output`) instead of a tool call.
- `ANTHROPIC_API_KEY` is removed from its environment so it always uses the subscription.
- Claude Code is installed in the image, pinned by `CLAUDE_CODE_VERSION` in the
  Dockerfile (auto-update off). Bump it deliberately and rebuild.

Why a token from `claude setup-token` and not the login in `~/.claude/.credentials.json`:
that file is Claude Code's interactive login. It rotates, and a copy refreshing itself
inside the container could log out Claude Code on your laptop. The setup token is
made for headless use and lives only in `.env`.

On the Pi 3B+, starting Claude Code takes extra seconds and a few hundred MB of RAM per
call; measure it, and consider `api` there if it's too slow.

## api

```sh
# platform.claude.com → API Keys → Create key (add a little credit under Billing)
# .env:
#   CLAUDE_BACKEND=api
#   ANTHROPIC_API_KEY=sk-ant-...
```

Uses the Anthropic Python SDK directly (`robot/brain.py: _ask_claude`) with a `speak` tool.

## Neither yet?

`ROBOT_DRY_RUN=1` runs everything except the Claude call and logs the prompt instead.
