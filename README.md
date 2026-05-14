# panda-cli

Single entry point for the PandaPoints ecosystem. One command starts the full
local dev stack — Hardhat node, contract deploy, trade simulator, price poller,
and the Next.js dapp — in the correct order, each in its own console window.

## Usage

```
python panda.py <command> [args]
```

### Full dev stack

```bash
python panda.py dev          # start everything, Ctrl+C to stop all
python panda.py stop         # kill all tracked services from another terminal
python panda.py status       # table of running PIDs
```

`dev` startup order:

1. Hardhat node (polls until RPC is ready)
2. `scramble_health.py` — deploy + seed contract (blocking)
3. `trade_sim.py` — fuzzy buy/sell transactions
4. `price_poller.py --local` — continuous price history
5. `yarn dev` — Next.js dapp on port 3000

### Individual services

```bash
# testenv
python panda.py testenv start     # hardhat node + deploy + seed
python panda.py testenv sim       # trade_sim.py only
python panda.py testenv reset     # stop everything, fresh redeploy

# dapp
python panda.py dapp dev          # yarn dev (port 3000)
python panda.py dapp poller       # price_poller.py --local
python panda.py dapp backfill     # backfill.py --local (blocking)

# content pipeline
python panda.py rotman server                         # rotman web UI
python panda.py rotman generate bitcoinfacil "topic"  # run pipeline
python panda.py rotman queue                          # show topic queue

# tooling
python panda.py bench run         # ollama-bench (blocking)
python panda.py gitmanager        # gitmanager server (port 8000)
python panda.py conduler          # conduler server (port 7071)
```

## Convenience wrapper

A `panda.bat` file at `workspace_root<\` lets you run `panda <command>` from
any terminal opened in that directory:

```bat
@echo off
python "%~dp0panda-cli\panda.py" %*
```

## PID tracking

Running services are tracked in `workspace_root<\.panda\pids.json`.
`panda stop` reads that file and kills everything. Safe to delete manually
if it gets out of sync.

## Adding new services

Each service is a ~5-line function in `panda.py`:

```python
def cmd_myservice():
    _log("Starting myservice...")
    return _launch("myservice", [sys.executable, "main.py"], P["myservice"])
```

Then add an entry to the `P` dict, wire it into `main()`, and it's done.
