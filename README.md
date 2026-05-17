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
