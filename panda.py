#!/usr/bin/env python3
"""
panda.py - PandaPoints Ecosystem Launcher

Single entry point for the entire PandaPoints dev ecosystem.
Starts, stops, and monitors all services from one place.

Usage
-----
    python panda.py dev                              # full local dev stack
    python panda.py testenv start                    # hardhat node + deploy/seed
    python panda.py testenv sim                      # trade simulator
    python panda.py testenv reset                    # stop all, fresh redeploy
    python panda.py dapp dev                         # yarn dev (Next.js)
    python panda.py dapp poller                      # price_poller.py --local
    python panda.py dapp backfill                    # backfill.py --local
    python panda.py rotman server                    # rotman web UI
    python panda.py rotman generate <channel> [topic]
    python panda.py rotman queue                     # show topic queue
    python panda.py bench run                        # ollama-bench
    python panda.py gitmanager                       # gitmanager server
    python panda.py conduler                         # conduler server
    python panda.py llm start                        # start llama-swap on :8080
    python panda.py llm stop                         # stop llama-swap
    python panda.py llm status                       # check LLM health + loaded models
    python panda.py vps ssh                          # open SSH session to VPS
    python panda.py vps status                       # pm2 + screen + disk + memory
    python panda.py vps logs pp                      # pm2 logs for dapp
    python panda.py vps logs bot                     # screen hardcopy for telegram bot
    python panda.py vps restart pp                   # pm2 restart dapp
    python panda.py vps deploy pp                    # git pull + pm2 restart dapp
    python panda.py vps send <local> <remote>        # scp file to VPS
    python panda.py status                           # show running services
    python panda.py stop                             # stop all tracked services
    python panda.py -h | --help
"""

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# == Paths =====================================================================

ROOT = Path(__file__).resolve().parent.parent

P = {
    "testenv":    ROOT / "pp-testenv",
    "dapp":       ROOT / "pandapoints-dapp",
    "rotman":     ROOT / "rotman",
    "bench":      ROOT / "ollama-bench",
    "gitmanager": ROOT / "gitmanager",
    "conduler":   ROOT / "conduler",
}

import shutil as _shutil

def _find_node_bin(name: str) -> str:
    found = _shutil.which(name)
    if found:
        return found
    fallback = Path(r"C:\Program Files\nodejs") / (name + ".cmd")
    if fallback.exists():
        return str(fallback)
    return name

NPM  = _find_node_bin("npm")
NPX  = _find_node_bin("npx")
YARN = _find_node_bin("yarn")

PANDA_DIR = ROOT / ".panda"
PIDS_FILE = PANDA_DIR / "pids.json"

HARDHAT_PORT    = 8545
DAPP_PORT       = 3000
GITMANAGER_PORT = 8765
CONDULER_PORT   = 7071
ROTMAN_PORT     = 7070
LLAMA_SWAP_PORT = 8080

LLAMA_SWAP_EXE_DEFAULT = Path(r"C:\llama.cpp\llama-swap.exe")
LLAMA_SWAP_CONFIG      = Path(r"C:\llama.cpp\config.yaml")

# == VPS config ================================================================

VPS_HOST    = os.environ.get("PANDA_VPS_HOST", "")
VPS_USER    = os.environ.get("PANDA_VPS_USER", "")
VPS_KEY     = os.environ.get("PANDA_VPS_KEY",  str(Path.home() / ".ssh" / "mcp_ssh_ed25519"))

# pm2 app name -> repo path on VPS (git-deployed apps only)
VPS_PM2_REPOS = {
    "pp": "remote_project_path<",
}

# all pm2 apps — supports logs + restart (no git deploy required)
VPS_PM2_APPS = ["pp", "telegramBot"]

# screen session names (empty — bot migrated to pm2)
VPS_SCREENS = []


# == Python resolver ===========================================================

def _py(project_key: str) -> str:
    venv_py = P[project_key] / "venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


def _yarn() -> list:
    if Path(YARN).exists():
        return [YARN]
    user_yarn = Path(os.environ.get("APPDATA", "")) / "npm" / "yarn.cmd"
    if user_yarn.exists():
        return [str(user_yarn)]
    return [NPX, "yarn"]


# == PID tracking ==============================================================

def _pids_load() -> dict:
    try:
        return json.loads(PIDS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pids_save(pids: dict):
    PANDA_DIR.mkdir(parents=True, exist_ok=True)
    PIDS_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False


def _register(name: str, proc: "subprocess.Popen[bytes]", label: str):
    pids = _pids_load()
    pids[name] = {
        "pid":     proc.pid,
        "cmd":     label,
        "started": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _pids_save(pids)


def _kill(pid: int, name: str):
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.kill(pid, signal.SIGTERM)
        _log(f"stopped {name} (PID {pid})")
    except Exception as exc:
        _log(f"could not stop {name} (PID {pid}): {exc}")


# == Logging ===================================================================

def _log(msg: str, prefix: str = "panda"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{prefix}] {msg}", flush=True)


# == Process launchers =========================================================

def _launch(name: str, cmd: list, cwd: Path) -> "subprocess.Popen[bytes]":
    kwargs: dict = {"cwd": str(cwd)}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL

    proc = subprocess.Popen(cmd, **kwargs)
    label = " ".join(str(c) for c in cmd)
    _register(name, proc, label)
    _log(f"{name} started (PID {proc.pid})")
    return proc


def _run(cmd: list, cwd: Path, label: str):
    _log(f"running: {label}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        raise RuntimeError(f"'{label}' failed (exit {result.returncode})")


# == SSH helpers ===============================================================

def _ssh_base() -> list:
    """Base ssh command with the MCP key."""
    return ["ssh", "-i", VPS_KEY, f"{VPS_USER}@{VPS_HOST}"]


def _ssh_run(remote_cmd: str) -> int:
    """Run a command on the VPS, streaming output. Returns exit code."""
    result = subprocess.run(_ssh_base() + [remote_cmd])
    return result.returncode


def _ssh_capture(remote_cmd: str) -> tuple[str, int]:
    """Run a command on the VPS, capture output. Returns (output, exit_code)."""
    result = subprocess.run(
        _ssh_base() + [remote_cmd],
        capture_output=True, text=True,
    )
    out = (result.stdout + result.stderr).strip()
    return out, result.returncode


# == Wait helpers ==============================================================

def _wait_rpc(port: int, timeout: int = 45, label: str = "RPC") -> bool:
    url  = f"http://127.0.0.1:{port}"
    body = json.dumps({
        "jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1
    }).encode()
    deadline = time.time() + timeout
    sys.stdout.write(f"    waiting for {label}")
    sys.stdout.flush()
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=2)
            sys.stdout.write(" ready\n")
            sys.stdout.flush()
            return True
        except Exception:
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(1)
    sys.stdout.write(" TIMEOUT\n")
    return False


def _wait_http(port: int, path: str = "/", timeout: int = 30, label: str = "HTTP") -> bool:
    url = f"http://127.0.0.1:{port}{path}"
    deadline = time.time() + timeout
    sys.stdout.write(f"    waiting for {label}")
    sys.stdout.flush()
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            sys.stdout.write(" ready\n")
            sys.stdout.flush()
            return True
        except urllib.error.HTTPError:
            sys.stdout.write(" ready\n")
            sys.stdout.flush()
            return True
        except Exception:
            sys.stdout.write(".")
            sys.stdout.flush()
            time.sleep(1)
    sys.stdout.write(" TIMEOUT\n")
    return False


def _open_browser(url: str):
    _log(f"opening {url}")
    webbrowser.open(url)


# == VPS commands ==============================================================

def cmd_vps_ssh():
    """Open an interactive SSH session to the VPS."""
    _log(f"Connecting to {VPS_USER}@{VPS_HOST}...")
    subprocess.run(_ssh_base())


def cmd_vps_status():
    """Show pm2 list, screen sessions, disk and memory on the VPS."""
    print()
    print("  ── pm2 ─────────────────────────────────────")
    _ssh_run("pm2 list")
    print()
    print("  ── screen sessions ─────────────────────────")
    _ssh_run("screen -ls 2>&1 || true")
    print()
    print("  ── disk ─────────────────────────────────────")
    _ssh_run("df -h --output=source,size,used,avail,pcent,target | column -t")
    print()
    print("  ── memory ───────────────────────────────────")
    _ssh_run("free -h")
    print()


def cmd_vps_logs(target: str):
    """
    Stream recent logs for a VPS service.
    target: pm2 app name (e.g. 'pp') or screen session name (e.g. 'bot')
    """
    if target in VPS_PM2_APPS:
        _log(f"pm2 logs for '{target}' (last 50 lines)...")
        _ssh_run(
            f"echo '=== OUT ===' && tail -n 50 ~/.pm2/logs/{target}-out.log 2>/dev/null; "
            f"echo '=== ERROR ===' && tail -n 50 ~/.pm2/logs/{target}-error.log 2>/dev/null"
        )
    elif target in VPS_SCREENS:
        _log(f"screen hardcopy for '{target}'...")
        tmp = f"/tmp/panda_screen_{target}.txt"
        _ssh_run(f"screen -S {target} -X hardcopy {tmp} && sleep 0.2 && cat {tmp} && rm -f {tmp}")
    else:
        known = list(VPS_PM2_REPOS.keys()) + VPS_SCREENS
        print(f"Unknown target '{target}'. Known: {known}")
        sys.exit(1)


def cmd_vps_restart(name: str):
    """Restart a pm2 app on the VPS."""
    if name not in VPS_PM2_APPS:
        print(f"Unknown pm2 app '{name}'. Known: {VPS_PM2_APPS}")
        sys.exit(1)
    _log(f"Restarting pm2 app '{name}' on VPS...")
    code = _ssh_run(f"pm2 restart {name} && pm2 list")
    if code == 0:
        _log("Restart successful.")
    else:
        _log(f"Restart failed (exit {code}).")


def cmd_vps_send(local_path: str, remote_path: str):
    """Upload a local file to the VPS via scp."""
    _log(f"Sending {local_path} -> {VPS_USER}@{VPS_HOST}:{remote_path}")
    result = subprocess.run([
        "scp", "-i", VPS_KEY,
        local_path,
        f"{VPS_USER}@{VPS_HOST}:{remote_path}"
    ])
    if result.returncode == 0:
        _log("File sent successfully.")
    else:
        _log(f"scp failed (exit {result.returncode}).")


def cmd_vps_deploy(name: str):
    """git pull + pm2 restart for a VPS app."""
    if name not in VPS_PM2_REPOS:
        print(f"Unknown app '{name}'. Known: {list(VPS_PM2_REPOS.keys())}")
        sys.exit(1)
    repo = VPS_PM2_REPOS[name]
    _log(f"Deploying '{name}': git pull {repo} + pm2 restart...")
    code = _ssh_run(f"cd {repo} && git pull && pm2 restart {name} && pm2 list")
    if code == 0:
        _log("Deploy successful.")
    else:
        _log(f"Deploy failed (exit {code}).")


# == Existing commands =========================================================

def cmd_testenv_start():
    _log("Starting Hardhat node...")
    proc_hh = _launch("hardhat", [NPX, "hardhat", "node"], P["testenv"])
    if not _wait_rpc(HARDHAT_PORT, timeout=45, label="Hardhat"):
        raise RuntimeError("Hardhat node did not respond in time.")
    _log("Deploying and seeding contract (scramble_health.py)...")
    _run([_py("testenv"), "scramble_health.py"], P["testenv"], "scramble_health.py")
    _log("Contract deployed and seeded.")
    return proc_hh


def cmd_testenv_sim():
    _log("Starting trade simulator...")
    return _launch("trade_sim", [_py("testenv"), "trade_sim.py"], P["testenv"])


def cmd_testenv_reset():
    _log("Resetting dev environment...")
    pids = _pids_load()
    for name in ("hardhat", "trade_sim", "price_poller", "dapp"):
        info = pids.get(name)
        if info and _pid_alive(info["pid"]):
            _kill(info["pid"], name)
    _pids_save({})
    time.sleep(2)
    cmd_testenv_start()


def cmd_dapp_dev():
    _log("Starting Next.js dapp...")
    proc = _launch("dapp", _yarn() + ["dev"], P["dapp"])
    if _wait_http(DAPP_PORT, label="dapp"):
        _open_browser(f"http://localhost:{DAPP_PORT}")
    return proc


def cmd_dapp_poller():
    _log("Starting price poller (local)...")
    return _launch("price_poller", [sys.executable, "scripts/price_poller.py", "--local"], P["dapp"])


def cmd_dapp_backfill():
    _log("Running backfill (local)...")
    _run([sys.executable, "scripts/backfill.py", "--local"], P["dapp"], "backfill.py --local")


def cmd_rotman_server():
    _log("Starting rotman server...")
    proc = _launch("rotman", [_py("rotman"), "server.py"], P["rotman"])
    if _wait_http(ROTMAN_PORT, label="rotman"):
        _open_browser(f"http://localhost:{ROTMAN_PORT}")
    return proc


def cmd_rotman_generate(channel, topic):
    if not channel:
        print("usage: panda rotman generate <channel> [topic]")
        sys.exit(1)
    cmd = [_py("rotman"), "pipeline.py", channel]
    if topic:
        cmd += ["--topic", topic]
    _run(cmd, P["rotman"], f"rotman pipeline {channel}")


def cmd_rotman_queue():
    _run([_py("rotman"), "topic_queue.py", "--list"], P["rotman"], "rotman queue")


def cmd_bench_run():
    _run([sys.executable, "bench.py"], P["bench"], "ollama-bench")


def cmd_gitmanager():
    _log("Starting gitmanager server...")
    proc = _launch("gitmanager", [sys.executable, "server.py"], P["gitmanager"])
    if _wait_http(GITMANAGER_PORT, label="gitmanager"):
        _open_browser(f"http://localhost:{GITMANAGER_PORT}")
    return proc


def cmd_conduler():
    _log("Starting conduler server...")
    proc = _launch("conduler", [sys.executable, "main.py"], P["conduler"])
    if _wait_http(CONDULER_PORT, label="conduler"):
        _open_browser(f"http://localhost:{CONDULER_PORT}")
    return proc


def _find_llama_swap_exe() -> str | None:
    env_override = os.environ.get("LLAMA_SWAP_EXE")
    if env_override and Path(env_override).exists():
        return env_override
    if LLAMA_SWAP_EXE_DEFAULT.exists():
        return str(LLAMA_SWAP_EXE_DEFAULT)
    found = _shutil.which("llama-swap")
    if found:
        return found
    return None


def cmd_llm_start():
    pids = _pids_load()
    info = pids.get("llama-swap")
    if info and _pid_alive(info["pid"]):
        _log(f"llama-swap already running (PID {info['pid']})")
        return
    exe = _find_llama_swap_exe()
    if not exe:
        raise RuntimeError(
            f"llama-swap binary not found.\n"
            f"  Expected : {LLAMA_SWAP_EXE_DEFAULT}\n"
            f"  Override : set the LLAMA_SWAP_EXE environment variable."
        )
    if not LLAMA_SWAP_CONFIG.exists():
        raise RuntimeError(f"llama-swap config not found: {LLAMA_SWAP_CONFIG}")
    _log(f"Starting llama-swap ({exe})...")
    proc = _launch(
        "llama-swap",
        [exe, "--config", str(LLAMA_SWAP_CONFIG), "--listen", f"0.0.0.0:{LLAMA_SWAP_PORT}"],
        LLAMA_SWAP_EXE_DEFAULT.parent,
    )
    _wait_http(LLAMA_SWAP_PORT, path="/v1/models", timeout=30, label="llama-swap")
    return proc


def cmd_llm_stop():
    pids = _pids_load()
    info = pids.get("llama-swap")
    if not info:
        _log("llama-swap is not tracked (not started via panda-cli).")
        return
    _kill(info["pid"], "llama-swap")
    del pids["llama-swap"]
    _pids_save(pids)


def cmd_llm_status():
    url = f"http://127.0.0.1:{LLAMA_SWAP_PORT}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data   = json.loads(resp.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            print(f"\n  llama-swap  :  online  (:{LLAMA_SWAP_PORT})")
            if models:
                for m in models:
                    print(f"    - {m}")
            else:
                print("    (no models currently loaded)")
    except Exception as exc:
        print(f"\n  llama-swap  :  OFFLINE  (:{LLAMA_SWAP_PORT})")
        print(f"  error  : {exc}")
        print(f"  start  : python panda.py llm start")
    print()


def _short_cmd(cmd: str) -> str:
    parts = cmd.split()
    while parts and (parts[0].lower().endswith(("python.exe", "python", "python3"))):
        parts = parts[1:]
    result = " ".join(parts)
    return result[:42] if result else cmd[:42]


def cmd_status():
    pids = _pids_load()
    if not pids:
        print("\n  No services currently tracked.\n")
        return
    print()
    print(f"  {'SERVICE':<16} {'PID':<8} {'STATUS':<10} {'STARTED (UTC)':<22} COMMAND")
    print(f"  {'-'*16} {'-'*8} {'-'*10} {'-'*22} {'-'*42}")
    for name, info in sorted(pids.items()):
        pid     = info.get("pid", 0)
        alive   = _pid_alive(pid)
        status  = "running" if alive else "stopped"
        started = info.get("started", "?")[:19].replace("T", " ")
        label   = _short_cmd(info.get("cmd", "?"))
        marker  = "+" if alive else "-"
        print(f"  [{marker}] {name:<14} {pid:<8} {status:<10} {started:<22} {label}")
    print()


def cmd_stop():
    pids = _pids_load()
    if not pids:
        _log("Nothing running.")
        return
    for name, info in pids.items():
        pid = info.get("pid", 0)
        _kill(pid, name)
    _pids_save({})
    _log("All services stopped.")


def cmd_dev():
    print()
    print("  +--------------------------------------------+")
    print("  |   PandaPoints - Full Dev Stack             |")
    print("  +--------------------------------------------+")
    print()
    _log("[1/5] Starting llama-swap (LLM server)...")
    try:
        cmd_llm_start()
    except RuntimeError as e:
        _log(f"WARNING: LLM server not started — {e}")
    _log("[2/5] Starting Hardhat node + deploying contract...")
    cmd_testenv_start()
    _log("[3/5] Starting trade simulator...")
    cmd_testenv_sim()
    _log("[4/5] Starting price poller (local)...")
    cmd_dapp_poller()
    _log("[5/5] Starting Next.js dapp...")
    cmd_dapp_dev()
    print()
    print("  +--------------------------------------------+")
    print(f"  |  Dapp         ->  http://localhost:{DAPP_PORT}      |")
    print(f"  |  Hardhat RPC  ->  http://127.0.0.1:{HARDHAT_PORT}   |")
    print(f"  |  LLM          ->  http://127.0.0.1:{LLAMA_SWAP_PORT}   |")
    print("  |                                            |")
    print("  |  Ctrl+C  ->  stop all services            |")
    print("  +--------------------------------------------+")
    print()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print()
        _log("Shutting down...")
        cmd_stop()


# == Help ======================================================================

HELP = """\
panda.py - PandaPoints Ecosystem Launcher

usage: python panda.py <command> [args]

commands:
  dev                                   full local dev stack + Ctrl+C teardown

  testenv start                         hardhat node + deploy + seed contract
  testenv sim                           start trade_sim.py
  testenv reset                         stop all, fresh redeploy

  dapp dev                              yarn dev  (Next.js, port 3000)
  dapp poller                           price_poller.py --local
  dapp backfill                         backfill.py --local  (blocking)

  rotman server                         rotman web UI
  rotman generate <channel> [topic]     run pipeline.py  (blocking)
  rotman queue                          show topic queue  (blocking)

  bench run                             ollama-bench  (blocking)

  gitmanager                            gitmanager server  (port 8765)
  conduler                              conduler server    (port 7071)

  llm start                             start llama-swap on :8080
  llm stop                              stop llama-swap
  llm status                            check LLM health + list loaded models

  vps ssh                               open interactive SSH session to VPS
  vps status                            pm2 + screen + disk + memory on VPS
  vps logs <pp|telegramBot>             tail logs for dapp (pp) or bot (telegramBot)
  vps restart <pp|telegramBot>          pm2 restart a VPS app
  vps deploy <pp>                       git pull + pm2 restart on VPS
  vps send <local_path> <remote_path>   scp a file to the VPS

  status                                table of tracked services + PIDs
  stop                                  kill all tracked services

  -h, --help                            show this message

vps env vars (required):
  PANDA_VPS_HOST    VPS hostname or IP address
  PANDA_VPS_USER    SSH user on the VPS
  PANDA_VPS_KEY     path to SSH private key (default: ~/.ssh/mcp_ssh_ed25519)
"""


# == Dispatch ==================================================================

def _unknown_sub(cmd: str, sub: str):
    print(f"unknown sub-command: '{cmd} {sub}'")
    print("Run 'python panda.py --help' for usage.")
    sys.exit(1)


def main():
    argv = sys.argv[1:]

    if not argv or argv[0] in ("-h", "--help"):
        print(HELP)
        return

    cmd = argv[0]

    try:
        if cmd == "dev":
            cmd_dev()

        elif cmd == "testenv":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "start": cmd_testenv_start()
            elif sub == "sim":   cmd_testenv_sim()
            elif sub == "reset": cmd_testenv_reset()
            else: _unknown_sub(cmd, sub)

        elif cmd == "dapp":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "dev":      cmd_dapp_dev()
            elif sub == "poller":   cmd_dapp_poller()
            elif sub == "backfill": cmd_dapp_backfill()
            else: _unknown_sub(cmd, sub)

        elif cmd == "rotman":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "server":   cmd_rotman_server()
            elif sub == "generate":
                cmd_rotman_generate(
                    argv[2] if len(argv) > 2 else None,
                    argv[3] if len(argv) > 3 else None,
                )
            elif sub == "queue": cmd_rotman_queue()
            else: _unknown_sub(cmd, sub)

        elif cmd == "bench":
            sub = argv[1] if len(argv) > 1 else ""
            if sub == "run": cmd_bench_run()
            else: _unknown_sub(cmd, sub)

        elif cmd == "vps":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "ssh":     cmd_vps_ssh()
            elif sub == "status":  cmd_vps_status()
            elif sub == "logs":
                target = argv[2] if len(argv) > 2 else ""
                if not target:
                    print("usage: panda vps logs <pp|bot>")
                    sys.exit(1)
                cmd_vps_logs(target)
            elif sub == "restart":
                name = argv[2] if len(argv) > 2 else ""
                if not name:
                    print("usage: panda vps restart <pp>")
                    sys.exit(1)
                cmd_vps_restart(name)
            elif sub == "deploy":
                name = argv[2] if len(argv) > 2 else ""
                if not name:
                    print("usage: panda vps deploy <pp>")
                    sys.exit(1)
                cmd_vps_deploy(name)
            elif sub == "send":
                local  = argv[2] if len(argv) > 2 else ""
                remote = argv[3] if len(argv) > 3 else ""
                if not local or not remote:
                    print("usage: panda vps send <local_path> <remote_path>")
                    sys.exit(1)
                cmd_vps_send(local, remote)
            else: _unknown_sub(cmd, sub)

        elif cmd == "gitmanager": cmd_gitmanager()
        elif cmd == "conduler":   cmd_conduler()
        elif cmd == "llm":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "start":  cmd_llm_start()
            elif sub == "stop":   cmd_llm_stop()
            elif sub == "status": cmd_llm_status()
            else: _unknown_sub(cmd, sub)
        elif cmd == "status":     cmd_status()
        elif cmd == "stop":       cmd_stop()
        else:
            print(f"unknown command: {cmd!r}")
            print("Run 'python panda.py --help' for usage.")
            sys.exit(1)

    except KeyboardInterrupt:
        print()
        _log("Interrupted.")
    except RuntimeError as exc:
        _log(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
