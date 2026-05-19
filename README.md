# panda-cli

Single entry point for the PandaPoints ecosystem. One command starts the full
local dev stack — Hardhat node, contract deploy, trade simulator, price poller,
and the Next.js dapp — in the correct order, each in its own console window.

## Installation

Clone this repo **directly inside your ecosystem root** — the same folder that
contains `pp-testenv`, `pandapoints-dapp`, `rotman`, etc.:

```
ecosystem-root/
  panda-cli/        <- this repo
  pp-testenv/
  pandapoints-dapp/
  rotman/
  conduler/
  gitmanager/
  ollama-bench/
```

`panda.py` derives all project paths from its own location (`__file__`), so it
works on any machine, any username, and any drive letter — no configuration
needed.

Node.js binaries (`npx`, `npm`, `yarn`) are resolved from PATH first, then fall
back to the Windows default install location (`C:\Program Files\nodejs`).

## Usage

```bash
python panda-cli/panda.py <command> [args]
```

Or drop the `panda.bat` wrapper at the ecosystem root for a shorter form:

```bat
@echo off
python "%~dp0panda-cli\panda.py" %*
```

Then just run `panda <command>` from the ecosystem root.

## Commands

### Full dev stack

```bash
panda dev          # start everything — Ctrl+C stops all services cleanly
panda stop         # kill all tracked services from another terminal
panda status       # table of running services and PIDs
```

`dev` startup order:

1. **Hardhat node** — polls until RPC responds before continuing
2. **`scramble_health.py`** — deploy + seed contract (blocking)
3. **`trade_sim.py`** — fuzzy buy/sell transactions
4. **`price_poller.py --local`** — continuous price history
5. **`yarn dev`** — Next.js dapp on port 3000

### Individual services

```bash
# testenv (pp-testenv)
panda testenv start     # hardhat node + deploy + seed
panda testenv sim       # trade_sim.py only
panda testenv reset     # stop everything, fresh redeploy

# dapp (pandapoints-dapp)
panda dapp dev          # yarn dev (port 3000)
panda dapp poller       # price_poller.py --local
panda dapp backfill     # backfill.py --local (blocking)

# content pipeline
panda rotman server                         # rotman web UI
panda rotman generate bitcoinfacil "topic"  # run pipeline (blocking)
panda rotman queue                          # show topic queue (blocking)

# tooling
panda bench run         # ollama-bench (blocking)
panda gitmanager        # gitmanager server (port 8000)
panda conduler          # conduler server (port 7071)
```


### Project registry

These commands read `workspace_root</gitmanager/projects.json` by default. Override
with `PROJECTS_JSON` when testing another registry.

```bash
panda projects list
panda projects show git-mcp
panda projects path mcp-ssh
panda projects status
```

### Git operations

Git commands resolve project names through the shared registry, so callers do not
need to pass full paths.

```bash
panda git ecosystem-status
panda git status git-mcp
panda git diff mcp-ssh
panda git diff-staged git-mcp
panda git log git-mcp --limit 10
panda git branches git-mcp
panda git add git-mcp server.py
panda git add git-mcp --all
panda git commit git-mcp "feat: add project commands"
```


### Python runner

Python commands auto-detect the nearest `venv/` or `.venv/` by walking up from
the script or working directory. Use `--venv` to force a specific environment and
`--timeout` to cap execution time.

```bash
panda py run workspace_root</rotman/main.py --timeout 60
panda py run-project rotman pipeline.py --timeout 120 -- bitcoinfacil --topic "topic"
panda py code "import sys; print(sys.executable)" --cwd git-mcp
```


## Controlled SSH commands

`panda ssh` is the safer replacement path for `mcp-ssh`. It keeps the same basic
security shape: configured SSH identity, allowlisted services/apps/repos, command
aliases instead of arbitrary shell, and a local audit log.

```bash
panda ssh config
panda ssh ping
panda ssh status
panda ssh audit --lines 50
panda ssh nginx status
panda ssh nginx logs --lines 50
panda ssh pm2 status
panda ssh pm2 logs pp --lines 50
panda ssh pm2 restart pp
panda ssh git status remote_project_path<
panda ssh git pull remote_project_path<
panda ssh read-file /etc/nginx/sites-enabled/default --lines 120
panda ssh list-dir remote_home<
panda ssh run-alias nginx-configtest
```

Configuration prefers `PANDA_*` env vars and falls back to the existing
`MCP_SSH_*` env vars where possible:

```text
PANDA_VPS_HOST / MCP_SSH_HOST
PANDA_VPS_PORT / MCP_SSH_PORT
PANDA_VPS_USER / MCP_SSH_USER
PANDA_VPS_KEY  / MCP_SSH_KEY_PATH
ssh_passphrase_env< / ssh_passphrase_env<
PANDA_SSH_ALLOWED_SERVICES / MCP_SSH_ALLOWED_SERVICES
PANDA_SSH_ALLOWED_PM2 / MCP_SSH_ALLOWED_PM2
PANDA_SSH_ALLOWED_SCREENS / MCP_SSH_ALLOWED_SCREENS
PANDA_SSH_ALLOWED_REPOS / MCP_SSH_ALLOWED_REPOS
PANDA_SSH_ALLOWED_COMMANDS / MCP_SSH_ALLOWED_COMMANDS
```

The audit log defaults to `%USERPROFILE%/.mcp-ssh/audit.log` for continuity with
`mcp-ssh`. If a key passphrase is configured, `panda ssh` uses Paramiko when
available; otherwise it uses non-interactive OpenSSH and expects the key to be
usable by `ssh.exe` or loaded in an agent.

## VPS commands

```bash
panda vps ssh                          # open interactive SSH session
panda vps status                       # pm2 + disk + memory on VPS
panda vps logs <pp|telegramBot>        # tail pm2 logs
panda vps restart <pp|telegramBot>     # pm2 restart
panda vps deploy <pp>                  # git pull + pm2 restart
panda vps send <local> <remote>        # scp a file to the VPS
```

Requires these env vars (no hardcoded defaults):

```
PANDA_VPS_HOST    VPS hostname or IP address
PANDA_VPS_USER    SSH user on the VPS
PANDA_VPS_KEY     path to SSH private key (default: ~/.ssh/mcp_ssh_ed25519)
```

## PID tracking

Running services are tracked in `<ecosystem-root>/.panda/pids.json`.
`panda stop` reads that file and kills everything cleanly. Safe to delete
manually if it gets out of sync.

## Adding a new service

Each service is a small function in `panda.py`. Add an entry to the `P` dict
at the top, write a `cmd_*` function, and wire it into `main()`:

```python
# 1. Add to P dict
P = {
    ...
    "myservice": ROOT / "myservice",
}

# 2. Write the command function
def cmd_myservice():
    _log("Starting myservice...")
    return _launch("myservice", [sys.executable, "main.py"], P["myservice"])

# 3. Wire into main()
elif cmd == "myservice":
    cmd_myservice()
```
