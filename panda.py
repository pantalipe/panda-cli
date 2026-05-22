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
import shlex
import subprocess
import sys
import time

# Ensure stdout/stderr handle Unicode on Windows (cp1252 terminals crash on box-drawing chars, pm2 arrows, etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# == Load .env ================================================================
# Auto-load a .env file from the panda-cli directory if present.
# Format: KEY=VALUE, one per line. Blank lines and # comments are ignored.
# Does NOT override variables that are already set in the environment.

def _load_dotenv():
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

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

# Registry shared with gitmanager. Override when testing another ecosystem.
PROJECTS_JSON = Path(os.environ.get("PROJECTS_JSON", str(ROOT / "gitmanager" / "projects.json")))

HARDHAT_PORT    = 8545
DAPP_PORT       = 3000
GITMANAGER_PORT = 8765
CONDULER_PORT   = 7071
ROTMAN_PORT     = 7070
LLAMA_SWAP_PORT = 8080

LLAMA_SWAP_EXE_DEFAULT = Path(r"C:\llama.cpp\llama-swap.exe")
LLAMA_SWAP_CONFIG      = Path(r"C:\llama.cpp\config.yaml")



def _env_csv(*names: str, default: str = "") -> list[str]:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return [item.strip() for item in value.split(",") if item.strip()]
    return [item.strip() for item in default.split(",") if item.strip()]


def _env_json(*names: str) -> dict:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
    return {}

# == VPS config ================================================================

VPS_HOST    = os.environ.get("PANDA_VPS_HOST") or os.environ.get("MCP_SSH_HOST", "")
VPS_PORT    = os.environ.get("PANDA_VPS_PORT") or os.environ.get("MCP_SSH_PORT", "22")
VPS_USER    = os.environ.get("PANDA_VPS_USER") or os.environ.get("MCP_SSH_USER", "")
VPS_KEY     = os.environ.get("PANDA_VPS_KEY") or os.environ.get("MCP_SSH_KEY_PATH", str(Path.home() / ".ssh" / "mcp_ssh_ed25519"))
VPS_KEY_PASS = os.environ.get("PANDA_SSH_KEY_PASSPHRASE") or os.environ.get("MCP_SSH_KEY_PASSPHRASE", "")

PANDA_SSH_AUDIT_LOG = Path(os.environ.get("PANDA_SSH_AUDIT_LOG", str(Path.home() / ".mcp-ssh" / "audit.log")))

# systemd services allowed for controlled status/restart/logs
VPS_SYSTEMD_SERVICES = _env_csv("PANDA_SSH_ALLOWED_SERVICES", "MCP_SSH_ALLOWED_SERVICES", default="nginx")

# all pm2 apps supported by controlled logs/restart
VPS_PM2_APPS = _env_csv("PANDA_SSH_ALLOWED_PM2", "MCP_SSH_ALLOWED_PM2", default="pp,telegramBot")

# screen session names supported by controlled inspection
VPS_SCREENS = _env_csv("PANDA_SSH_ALLOWED_SCREENS", "MCP_SSH_ALLOWED_SCREENS", default="")

# repo paths allowed for remote git status/pull
_ALLOWED_REPO_LIST = _env_csv("PANDA_SSH_ALLOWED_REPOS", "MCP_SSH_ALLOWED_REPOS", default="")
VPS_ALLOWED_REPOS = set(_ALLOWED_REPO_LIST)

# pm2 app name -> repo path on VPS (git-deployed apps only)
# Configure via PANDA_SSH_PM2_REPOS env var: "pp=/home/<user>/pp,bot=/home/<user>/bot"
VPS_PM2_REPOS = {}
for item in _env_csv("PANDA_SSH_PM2_REPOS", default=""):
    if "=" in item:
        name, repo = item.split("=", 1)
        VPS_PM2_REPOS[name.strip()] = repo.strip()

_CMD_DEFAULTS = {
    "systemctl-enable-nginx": "sudo -n systemctl enable nginx",
    "systemctl-disable-nginx": "sudo -n systemctl disable nginx",
    "systemctl-enable-pm2": "sudo -n systemctl enable pm2-panda",
    "pm2-startup": "pm2 startup systemd",
    "pm2-install-startup": "sudo env PATH=$PATH:/usr/bin /usr/local/lib/node_modules/pm2/bin/pm2 startup systemd -u <vps_user> --hp /home/<vps_user>",
    "pm2-save": "pm2 save",
    "pm2-resurrect": "pm2 resurrect",
    "nginx-configtest": "sudo -n nginx -t",
    "whoami": "whoami && id",
    "env-path": "echo $PATH",
}
VPS_ALLOWED_COMMANDS = {**_CMD_DEFAULTS, **_env_json("PANDA_SSH_ALLOWED_COMMANDS", "MCP_SSH_ALLOWED_COMMANDS")}

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
    """Base ssh command with the configured key."""
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-p", str(VPS_PORT), "-i", VPS_KEY, f"{VPS_USER}@{VPS_HOST}"]


def _is_ssh_auth_error(stderr_text: str) -> bool:
    """Return True if stderr indicates an SSH authentication failure."""
    markers = ("Permission denied", "publickey", "Authentication failed", "no mutual signature")
    return any(m in stderr_text for m in markers)


def _ssh_agent_unlock() -> bool:
    """Ensure the key is loaded in ssh-agent.

    Strategy:
    - If PANDA_SSH_KEY_PASSPHRASE is set: run ssh-add non-interactively via
      a temp SSH_ASKPASS helper script (works with OpenSSH on Windows).
    - Otherwise: run ssh-add interactively so the user is prompted once.

    Returns True if the key was successfully loaded.
    """
    # 1. Check agent availability
    check = subprocess.run(["ssh-add", "-l"], capture_output=True, text=True)
    if check.returncode == 2:
        print(
            "[ssh] ssh-agent is not running.\n"
            "      Start it as Administrator (once per system):\n"
            "        Set-Service ssh-agent -StartupType Automatic\n"
            "        Start-Service ssh-agent",
            file=sys.stderr,
        )
        return False

    # 2. Check if key is already loaded (ssh-add -L shows full public key with path comment)
    pubkeys = subprocess.run(["ssh-add", "-L"], capture_output=True, text=True)
    key_stem = Path(VPS_KEY).expanduser().stem
    if pubkeys.returncode == 0 and key_stem in pubkeys.stdout:
        return True  # Already loaded

    # 3. Add the key
    key_path = str(Path(VPS_KEY).expanduser())
    if VPS_KEY_PASS:
        # Non-interactive: write a temporary askpass helper
        import tempfile, textwrap
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as fh:
            askpass_path = fh.name
            # Escape backslashes in passphrase for safety
            safe_pass = VPS_KEY_PASS.replace("\\", "\\\\").replace('"', '\\"')
            fh.write(textwrap.dedent(f'''\
                import sys
                print("{safe_pass}")
            '''))
        try:
            env = {
                **os.environ,
                "SSH_ASKPASS": f"{sys.executable} {askpass_path}",
                "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": "1",  # Required by some OpenSSH builds to enable SSH_ASKPASS
            }
            result = subprocess.run(
                ["ssh-add", key_path],
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("[ssh] Key added to agent via passphrase from env.", file=sys.stderr)
                return True
            print(f"[ssh] ssh-add (non-interactive) failed: {result.stderr.strip()}", file=sys.stderr)
            return False
        finally:
            Path(askpass_path).unlink(missing_ok=True)
    else:
        # Interactive: prompt the user once
        print(f"[ssh] Adding key to agent (you will be prompted for the passphrase): {key_path}", file=sys.stderr)
        result = subprocess.run(["ssh-add", key_path])
        return result.returncode == 0


def _ssh_paramiko_exec(remote_cmd: str) -> tuple[str, str, int]:
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError("paramiko is not installed") from exc

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))

    key = None
    key_path = Path(VPS_KEY).expanduser()
    passphrase = VPS_KEY_PASS or None
    try:
        key = paramiko.Ed25519Key.from_private_key_file(str(key_path), password=passphrase)
    except paramiko.ssh_exception.SSHException:
        key = paramiko.RSAKey.from_private_key_file(str(key_path), password=passphrase)

    client.connect(
        hostname=VPS_HOST,
        port=int(VPS_PORT),
        username=VPS_USER,
        pkey=key,
        timeout=15,
        banner_timeout=15,
    )
    try:
        _, stdout, stderr = client.exec_command(remote_cmd, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        code = stdout.channel.recv_exit_status()
        return out, err, code
    finally:
        client.close()


def _ssh_run(remote_cmd: str) -> int:
    """Run a command on the VPS, streaming output. Returns exit code."""
    if VPS_KEY_PASS:
        out, err, code = _ssh_paramiko_exec(remote_cmd)
        if out:
            sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
            sys.stdout.buffer.write(b"\n")
        if err:
            sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
            sys.stderr.buffer.write(b"\n")
        return code
    # First attempt: BatchMode (non-interactive, fast fail on auth error)
    probe = subprocess.run(_ssh_base() + [remote_cmd], capture_output=True, text=True)
    if probe.returncode != 0 and _is_ssh_auth_error(probe.stderr):
        print("[ssh] Auth failed — key not in agent. Attempting ssh-add...", file=sys.stderr)
        if _ssh_agent_unlock():
            # Retry with streaming output
            return subprocess.run(_ssh_base() + [remote_cmd]).returncode
        # Unlock failed — surface original error
        print(probe.stderr.strip(), file=sys.stderr)
        return probe.returncode
    # Success or non-auth error — forward captured output
    if probe.stdout:
        sys.stdout.buffer.write(probe.stdout.encode("utf-8", errors="replace"))
    if probe.stderr:
        sys.stderr.buffer.write(probe.stderr.encode("utf-8", errors="replace"))
    return probe.returncode


def _ssh_capture(remote_cmd: str) -> tuple[str, int]:
    """Run a command on the VPS, capture output. Returns (output, exit_code)."""
    if VPS_KEY_PASS:
        out, err, code = _ssh_paramiko_exec(remote_cmd)
        combined = "\n".join(part for part in (out, err) if part).strip()
        return combined, code
    result = subprocess.run(_ssh_base() + [remote_cmd], capture_output=True, text=True)
    if result.returncode != 0 and _is_ssh_auth_error(result.stderr):
        print("[ssh] Auth failed — key not in agent. Attempting ssh-add...", file=sys.stderr)
        if _ssh_agent_unlock():
            result = subprocess.run(_ssh_base() + [remote_cmd], capture_output=True, text=True)
    out = (result.stdout + result.stderr).strip()
    return out, result.returncode




def _ssh_audit(action: str, detail: str, success: bool = True):
    status = "OK" if success else "FAIL"
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        PANDA_SSH_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(PANDA_SSH_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {status} | {action} | {detail}\n")
    except OSError as exc:
        print(f"warning: could not write audit log {PANDA_SSH_AUDIT_LOG}: {exc}", file=sys.stderr)


def _ssh_require_config():
    missing = []
    if not VPS_HOST:
        missing.append("PANDA_VPS_HOST or MCP_SSH_HOST")
    if not VPS_USER:
        missing.append("PANDA_VPS_USER or MCP_SSH_USER")
    if missing:
        raise RuntimeError("Missing VPS config: " + ", ".join(missing))


def _ssh_quote(value: str) -> str:
    return shlex.quote(value)


def _ssh_run_audited(action: str, detail: str, remote_cmd: str) -> int:
    _ssh_require_config()
    code = _ssh_run(remote_cmd)
    _ssh_audit(action, detail, success=(code == 0))
    return code


def _ssh_capture_audited(action: str, detail: str, remote_cmd: str) -> tuple[str, int]:
    _ssh_require_config()
    out, code = _ssh_capture(remote_cmd)
    _ssh_audit(action, detail, success=(code == 0))
    return out, code

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



# == Project registry ==========================================================

def _load_projects() -> dict:
    if not PROJECTS_JSON.exists():
        raise RuntimeError(f"projects.json not found: {PROJECTS_JSON}")
    with open(PROJECTS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("projects", data)


def _project_path(project: str) -> Path:
    projects = _load_projects()
    if project not in projects:
        available = ", ".join(sorted(projects.keys()))
        raise RuntimeError(f"Unknown project '{project}'. Available: {available}")
    entry = projects[project]
    raw = entry.get("path") if isinstance(entry, dict) else entry
    if not raw:
        raise RuntimeError(f"Project '{project}' has no path in {PROJECTS_JSON}")
    return Path(raw).expanduser()


def _project_entry(project: str):
    projects = _load_projects()
    if project not in projects:
        available = ", ".join(sorted(projects.keys()))
        raise RuntimeError(f"Unknown project '{project}'. Available: {available}")
    return projects[project]


def _require_project_arg(argv: list[str], usage: str) -> str:
    if not argv:
        print(usage)
        sys.exit(1)
    return argv[0]


def cmd_projects_list():
    projects = _load_projects()
    print()
    print(f"  {'PROJECT':<22} {'STATUS':<16} {'TYPE':<12} PATH")
    print(f"  {'-'*22} {'-'*16} {'-'*12} {'-'*40}")
    for name, entry in sorted(projects.items()):
        path = entry.get("path", "") if isinstance(entry, dict) else entry
        status = entry.get("status", "") if isinstance(entry, dict) else ""
        kind = entry.get("type", "") if isinstance(entry, dict) else ""
        print(f"  {name:<22} {status:<16} {kind:<12} {path}")
    print()


def cmd_projects_show(project: str):
    entry = _project_entry(project)
    print(json.dumps(entry, indent=2, ensure_ascii=False))


def cmd_projects_path(project: str):
    print(_project_path(project))


def cmd_projects_status():
    cmd_git_ecosystem_status()


# == Git commands ============================================================== 

def _git(project: str, args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    path = _project_path(project)
    if not path.exists():
        raise RuntimeError(f"Project path does not exist: {path}")
    cmd = ["git", "-c", f"safe.directory={path}", "-C", str(path)] + args
    return subprocess.run(cmd, text=True, capture_output=capture)


def _git_output(project: str, args: list[str]) -> str:
    result = _git(project, args, capture=True)
    out = (result.stdout or "").rstrip()
    err = (result.stderr or "").rstrip()
    if result.returncode != 0:
        detail = err or out or f"git exited with {result.returncode}"
        raise RuntimeError(detail)
    return out


def _git_branch(project: str) -> str:
    branch = _git_output(project, ["branch", "--show-current"])
    return branch or "(detached HEAD)"


def _git_status_counts(project: str) -> tuple[str, int, int, int, int]:
    status = _git_output(project, ["status", "--porcelain=v1", "-b"])
    branch = "unknown"
    staged = unstaged = untracked = ahead = 0
    for line in status.splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...")[0].strip()
            if "[ahead " in line:
                try:
                    ahead = int(line.split("[ahead ", 1)[1].split("]", 1)[0].split(",", 1)[0])
                except ValueError:
                    ahead = 0
            continue
        if line.startswith("??"):
            untracked += 1
            continue
        if len(line) >= 2:
            if line[0] != " ":
                staged += 1
            if line[1] != " ":
                unstaged += 1
    return branch, staged, unstaged, untracked, ahead


def cmd_git_status(project: str):
    print(_git_output(project, ["status", "--short", "--branch"]) or "Working tree clean.")


def cmd_git_diff(project: str, file_path: str = ""):
    args = ["diff"]
    if file_path:
        args += ["--", file_path]
    print(_git_output(project, args) or "(no unstaged changes)")


def cmd_git_diff_staged(project: str):
    print(_git_output(project, ["diff", "--cached"]) or "(no staged changes)")


def cmd_git_log(project: str, limit: int = 10):
    fmt = "%h %s (%cd) <%an>"
    print(_git_output(project, ["log", f"-{limit}", f"--pretty=format:{fmt}", "--date=short"]) or "(no commits)")


def cmd_git_branches(project: str):
    print(_git_output(project, ["branch", "-vv"]) or "(no branches)")


def cmd_git_add(project: str, files: list[str]):
    args = ["add"] + (files if files else ["-A"])
    result = _git(project, args, capture=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    print(f"Staged {'all changes' if not files else ', '.join(files)} in {project}.")


def cmd_git_commit(project: str, message_parts: list[str]):
    if not message_parts:
        print("usage: panda git commit <project> <message>")
        sys.exit(1)
    message = " ".join(message_parts)
    result = _git(project, ["commit", "-m", message], capture=True)
    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(out or f"git commit failed with exit {result.returncode}")
    print(out)


def cmd_git_push(project: str, args: list[str]):
    if len(args) > 2 or any(arg.startswith("-") for arg in args):
        print("usage: panda git push <project> [remote] [branch]")
        sys.exit(1)
    result = _git(project, ["push"] + args, capture=True)
    out = ((result.stdout or "") + (result.stderr or "")).strip()
    if result.returncode != 0:
        raise RuntimeError(out or f"git push failed with exit {result.returncode}")
    print(out or f"Pushed {project}.")


def cmd_git_ecosystem_status():
    projects = _load_projects()
    dirty = []
    clean = []
    other = []
    for name in sorted(projects.keys()):
        try:
            branch, staged, unstaged, untracked, ahead = _git_status_counts(name)
            parts = []
            if staged:
                parts.append(f"{staged} staged")
            if unstaged:
                parts.append(f"{unstaged} unstaged")
            if untracked:
                parts.append(f"{untracked} untracked")
            if ahead:
                parts.append(f"{ahead} to push")
            line = f"  {name} [{branch}] - {', '.join(parts) if parts else 'clean'}"
            (dirty if parts else clean).append(line)
        except Exception as exc:
            other.append(f"  {name} - error: {exc}")

    print("\nEcosystem status:\n")
    if dirty:
        print("Needs attention:")
        print("\n".join(dirty))
        print()
    if other:
        print("Errors:")
        print("\n".join(other))
        print()
    if clean:
        print("Clean:")
        print("\n".join(clean))
        print()
    print(f"{len(dirty)} of {len(projects)} projects have pending changes.")


def _parse_limit(args: list[str], default: int = 10) -> int:
    if not args:
        return default
    if len(args) == 1 and args[0].isdigit():
        return int(args[0])
    if len(args) == 2 and args[0] == "--limit" and args[1].isdigit():
        return int(args[1])
    print("usage: panda git log <project> [--limit N]")
    sys.exit(1)


# == Python runner commands ====================================================

def _clean_python_env() -> dict:
    blocked = {
        "VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT", "PYTHONPATH", "PYTHONHOME",
        "UV_PROJECT_ENVIRONMENT", "UV_PYTHON", "PYTHONINSPECT",
    }
    return {k: v for k, v in os.environ.items() if k not in blocked}


def _venv_python(venv_path: str) -> str:
    base = Path(venv_path).expanduser()
    candidates = [base / "Scripts" / "python.exe", base / "bin" / "python"]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RuntimeError(f"No Python found in venv: {venv_path}")


def _find_project_python(start_path: Path, venv_path: str = "") -> str:
    if venv_path:
        return _venv_python(venv_path)
    current = start_path if start_path.is_dir() else start_path.parent
    for _ in range(8):
        for name in ("venv", ".venv"):
            base = current / name
            candidates = [base / "Scripts" / "python.exe", base / "bin" / "python"]
            for candidate in candidates:
                if candidate.exists():
                    return str(candidate)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return sys.executable


def _split_py_args(args: list[str]) -> tuple[list[str], dict[str, str]]:
    options = {"timeout": "30", "venv": "", "cwd": ""}
    script_args = []
    i = 0
    pass_through = False
    while i < len(args):
        item = args[i]
        if pass_through:
            script_args.append(item)
        elif item == "--":
            pass_through = True
        elif item in ("--timeout", "--venv", "--cwd"):
            if i + 1 >= len(args):
                raise RuntimeError(f"Missing value for {item}")
            options[item[2:]] = args[i + 1]
            i += 1
        else:
            script_args.append(item)
        i += 1
    return script_args, options


def _format_python_result(result: subprocess.CompletedProcess, python_used: str) -> str:
    lines = [f"Python: {python_used}", f"Exit code: {result.returncode}"]
    stdout = (result.stdout or "").rstrip()
    stderr = (result.stderr or "").rstrip()
    if stdout:
        lines += ["", "-- stdout --", stdout]
    if stderr:
        lines += ["", "-- stderr --", stderr]
    if not stdout and not stderr:
        lines.append("(no output)")
    return "\n".join(lines)


def _run_python(python: str, args: list[str], cwd: Path, timeout: int):
    try:
        result = subprocess.run(
            [python] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_clean_python_env(),
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        print(f"Python: {python}\nExit code: -1\n\n-- stderr --\nTimeout: exceeded {timeout}s limit.")
        return
    print(_format_python_result(result, python))


def cmd_py_run(script_path: str, args: list[str]):
    script_args, options = _split_py_args(args)
    path = Path(script_path).expanduser()
    if not path.exists():
        raise RuntimeError(f"Python script not found: {path}")
    python = _find_project_python(path, options["venv"])
    _run_python(python, [str(path)] + script_args, path.parent, int(options["timeout"]))


def cmd_py_run_project(project: str, script_path: str, args: list[str]):
    script_args, options = _split_py_args(args)
    project_dir = _project_path(project)
    path = project_dir / script_path
    if not path.exists():
        raise RuntimeError(f"Python script not found: {path}")
    python = _find_project_python(path, options["venv"])
    _run_python(python, [str(path)] + script_args, path.parent, int(options["timeout"]))


def cmd_py_code(code: str, args: list[str]):
    _, options = _split_py_args(args)
    cwd_value = options["cwd"]
    if cwd_value:
        try:
            cwd = _project_path(cwd_value)
        except RuntimeError:
            cwd = Path(cwd_value).expanduser()
    else:
        cwd = Path.home()
    if not cwd.exists():
        raise RuntimeError(f"Working directory not found: {cwd}")
    python = _find_project_python(cwd, options["venv"])
    _run_python(python, ["-c", code], cwd, int(options["timeout"]))


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


# == Controlled SSH commands ===================================================

def cmd_ssh_ping():
    out, code = _ssh_capture_audited("ping", VPS_HOST, 'echo "host=$(hostname)" && uptime')
    print(out)
    print(f"[exit code: {code}]")
    sys.exit(code) if code else None


def cmd_ssh_disk():
    code = _ssh_run_audited("disk_usage", VPS_HOST, "df -h --output=source,size,used,avail,pcent,target | column -t")
    sys.exit(code) if code else None


def cmd_ssh_memory():
    code = _ssh_run_audited("memory_usage", VPS_HOST, "free -h && echo '---' && ps aux --sort=-%mem | head -10")
    sys.exit(code) if code else None


def cmd_ssh_uptime():
    code = _ssh_run_audited("uptime", VPS_HOST, "uptime && echo '' && w")
    sys.exit(code) if code else None


def cmd_ssh_status():
    cmd_ssh_pm2_status()
    print()
    cmd_ssh_disk()
    print()
    cmd_ssh_memory()


def cmd_ssh_service_status(service: str):
    if service not in VPS_SYSTEMD_SERVICES:
        _ssh_audit("service_status", f"BLOCKED: {service}", success=False)
        raise RuntimeError(f"Service '{service}' is not allowed. Allowed: {VPS_SYSTEMD_SERVICES}")
    code = _ssh_run_audited("service_status", service, f"sudo -n systemctl status {_ssh_quote(service)} --no-pager -l")
    sys.exit(code) if code else None


def cmd_ssh_service_restart(service: str):
    if service not in VPS_SYSTEMD_SERVICES:
        _ssh_audit("service_restart", f"BLOCKED: {service}", success=False)
        raise RuntimeError(f"Service '{service}' is not allowed. Allowed: {VPS_SYSTEMD_SERVICES}")
    code = _ssh_run_audited("service_restart", service, f"sudo -n systemctl restart {_ssh_quote(service)} && echo '{service} restarted OK'")
    sys.exit(code) if code else None


def cmd_ssh_service_logs(service: str, lines: int = 50):
    if service not in VPS_SYSTEMD_SERVICES:
        _ssh_audit("service_logs", f"BLOCKED: {service}", success=False)
        raise RuntimeError(f"Service '{service}' is not allowed. Allowed: {VPS_SYSTEMD_SERVICES}")
    lines = min(int(lines), 200)
    code = _ssh_run_audited("service_logs", f"{service} last={lines}", f"sudo -n journalctl -u {_ssh_quote(service)} -n {lines} --no-pager")
    sys.exit(code) if code else None


def cmd_ssh_nginx_status():
    cmd_ssh_service_status("nginx")


def cmd_ssh_nginx_restart():
    cmd_ssh_service_restart("nginx")


def cmd_ssh_nginx_logs(lines: int = 50):
    lines = min(int(lines), 200)
    code = _ssh_run_audited("nginx_logs", f"last={lines}", f"sudo -n tail -n {lines} /var/log/nginx/error.log")
    sys.exit(code) if code else None


def cmd_ssh_pm2_status():
    code = _ssh_run_audited("pm2_status", VPS_HOST, "pm2 list")
    sys.exit(code) if code else None


def cmd_ssh_pm2_restart(name: str):
    if name not in VPS_PM2_APPS:
        _ssh_audit("pm2_restart", f"BLOCKED: {name}", success=False)
        raise RuntimeError(f"PM2 app '{name}' is not allowed. Allowed: {VPS_PM2_APPS}")
    code = _ssh_run_audited("pm2_restart", name, f"pm2 restart {_ssh_quote(name)} && pm2 list")
    sys.exit(code) if code else None


def cmd_ssh_pm2_logs(name: str, lines: int = 50):
    if name not in VPS_PM2_APPS:
        _ssh_audit("pm2_logs", f"BLOCKED: {name}", success=False)
        raise RuntimeError(f"PM2 app '{name}' is not allowed. Allowed: {VPS_PM2_APPS}")
    lines = min(int(lines), 200)
    safe_name = _ssh_quote(name)
    code = _ssh_run_audited(
        "pm2_logs",
        f"{name} last={lines}",
        f"echo '=== OUT ===' && tail -n {lines} ~/.pm2/logs/{safe_name}-out.log 2>/dev/null; "
        f"echo '=== ERROR ===' && tail -n {lines} ~/.pm2/logs/{safe_name}-error.log 2>/dev/null",
    )
    sys.exit(code) if code else None


def cmd_ssh_screen_list():
    code = _ssh_run_audited("screen_list", VPS_HOST, "screen -ls 2>&1 || true")
    sys.exit(code) if code else None


def cmd_ssh_screen_logs(name: str):
    if name not in VPS_SCREENS:
        _ssh_audit("screen_logs", f"BLOCKED: {name}", success=False)
        raise RuntimeError(f"Screen '{name}' is not allowed. Allowed: {VPS_SCREENS}")
    tmp = f"/tmp/panda_screen_{name}.txt"
    code = _ssh_run_audited("screen_logs", name, f"screen -S {_ssh_quote(name)} -X hardcopy {_ssh_quote(tmp)} && sleep 0.2 && cat {_ssh_quote(tmp)} && rm -f {_ssh_quote(tmp)}")
    sys.exit(code) if code else None


def cmd_ssh_git_status(repo_path: str):
    if repo_path not in VPS_ALLOWED_REPOS:
        _ssh_audit("git_status", f"BLOCKED: {repo_path}", success=False)
        raise RuntimeError(f"Repo path '{repo_path}' is not allowed. Allowed: {sorted(VPS_ALLOWED_REPOS)}")
    code = _ssh_run_audited("git_status", repo_path, f"cd {_ssh_quote(repo_path)} && git status && echo '---' && git log --oneline -5")
    sys.exit(code) if code else None


def cmd_ssh_git_pull(repo_path: str):
    if repo_path not in VPS_ALLOWED_REPOS:
        _ssh_audit("git_pull", f"BLOCKED: {repo_path}", success=False)
        raise RuntimeError(f"Repo path '{repo_path}' is not allowed. Allowed: {sorted(VPS_ALLOWED_REPOS)}")
    code = _ssh_run_audited("git_pull", repo_path, f"cd {_ssh_quote(repo_path)} && git pull 2>&1")
    sys.exit(code) if code else None


def cmd_ssh_read_file(remote_path: str, lines: int = 500):
    lines = min(int(lines), 500)
    code = _ssh_run_audited("read_file", remote_path, f"head -{lines} {_ssh_quote(remote_path)} 2>&1")
    sys.exit(code) if code else None


def cmd_ssh_list_dir(remote_path: str):
    code = _ssh_run_audited("list_dir", remote_path, f"ls -lah {_ssh_quote(remote_path)} 2>&1")
    sys.exit(code) if code else None


def cmd_ssh_run_alias(alias: str):
    if alias not in VPS_ALLOWED_COMMANDS:
        _ssh_audit("run_command", f"BLOCKED unknown alias: {alias!r}", success=False)
        raise RuntimeError(f"Unknown alias '{alias}'. Available: {sorted(VPS_ALLOWED_COMMANDS.keys())}")
    command = VPS_ALLOWED_COMMANDS[alias]
    code = _ssh_run_audited("run_command", f"{alias!r} -> {command!r}", command)
    sys.exit(code) if code else None


def cmd_ssh_audit(lines: int = 30):
    lines = min(int(lines), 100)
    if not PANDA_SSH_AUDIT_LOG.exists():
        print("Audit log is empty.")
        return
    entries = PANDA_SSH_AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    print("\n".join(entries[-lines:]))


def cmd_ssh_config():
    print(json.dumps({
        "host": VPS_HOST,
        "port": VPS_PORT,
        "user": VPS_USER,
        "key_path": VPS_KEY,
        "passphrase_set": bool(VPS_KEY_PASS),
        "allowed_systemd_services": VPS_SYSTEMD_SERVICES,
        "allowed_pm2_apps": VPS_PM2_APPS,
        "allowed_screen_sessions": VPS_SCREENS,
        "allowed_repo_paths": sorted(VPS_ALLOWED_REPOS),
        "allowed_aliases": sorted(VPS_ALLOWED_COMMANDS.keys()),
        "audit_log": str(PANDA_SSH_AUDIT_LOG),
    }, indent=2))


def _parse_lines(args: list[str], default: int = 50) -> int:
    if not args:
        return default
    if len(args) == 1 and args[0].isdigit():
        return int(args[0])
    if len(args) == 2 and args[0] == "--lines" and args[1].isdigit():
        return int(args[1])
    raise RuntimeError("Use [--lines N]")


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


def cmd_bench_all(delay: int = 15):
    _run([sys.executable, "bench_all.py", "--delay", str(delay)], P["bench"], "ollama-bench all")


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

  bench run                             ollama-bench (todos os modelos juntos)  (blocking)
  bench all [delay]                     um modelo por vez, delay seg entre eles (padrão 15)  (blocking)

  gitmanager                            gitmanager server  (port 8765)
  conduler                              conduler server    (port 7071)

  llm start                             start llama-swap on :8080
  llm stop                              stop llama-swap
  llm status                            check LLM health + list loaded models

  projects list                          list projects from gitmanager/projects.json
  projects show <project>                show registry metadata for a project
  projects path <project>                print resolved project path
  projects status                        same as git ecosystem-status

  git ecosystem-status                   Git health summary for all registered projects
  git status <project>                   git status --short --branch
  git diff <project> [file]              unstaged diff
  git diff-staged <project>              staged diff
  git log <project> [--limit N]          recent commits
  git branches <project>                 local branches
  git add <project> [file ...|--all]     stage files or all changes
  git commit <project> <message>         commit staged changes
  git push <project> [remote] [branch]   push committed changes

  py run <script_path>                  run an absolute/local Python script
  py run-project <project> <script>     run a Python script inside a project
  py code <code> [--cwd <project|path>] run inline Python code


  ssh ping                              controlled VPS connectivity check
  ssh status                            pm2 + disk + memory through allowlist
  ssh config                            show SSH config without secrets
  ssh audit [--lines N]                 show local audit log
  ssh nginx <status|restart|logs>       controlled nginx operations
  ssh service <status|restart|logs>     controlled systemd service operations
  ssh pm2 <status|logs|restart>         controlled pm2 operations
  ssh git <status|pull> <repo_path>     controlled remote git operations
  ssh read-file <remote_path>           read first lines of a remote file
  ssh list-dir <remote_path>            list a remote directory
  ssh run-alias <alias>                 run a pre-approved command alias

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
            if   sub == "run": cmd_bench_run()
            elif sub == "all":
                delay = int(argv[2]) if len(argv) > 2 else 15
                cmd_bench_all(delay)
            else: _unknown_sub(cmd, sub)


        elif cmd == "projects":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "list":   cmd_projects_list()
            elif sub == "show":   cmd_projects_show(_require_project_arg(argv[2:], "usage: panda projects show <project>"))
            elif sub == "path":   cmd_projects_path(_require_project_arg(argv[2:], "usage: panda projects path <project>"))
            elif sub == "status": cmd_projects_status()
            else: _unknown_sub(cmd, sub)

        elif cmd == "git":
            sub = argv[1] if len(argv) > 1 else ""
            if sub == "ecosystem-status":
                cmd_git_ecosystem_status()
            elif sub == "status":
                cmd_git_status(_require_project_arg(argv[2:], "usage: panda git status <project>"))
            elif sub == "diff":
                project = _require_project_arg(argv[2:], "usage: panda git diff <project> [file]")
                cmd_git_diff(project, argv[3] if len(argv) > 3 else "")
            elif sub == "diff-staged":
                cmd_git_diff_staged(_require_project_arg(argv[2:], "usage: panda git diff-staged <project>"))
            elif sub == "log":
                project = _require_project_arg(argv[2:], "usage: panda git log <project> [--limit N]")
                cmd_git_log(project, _parse_limit(argv[3:]))
            elif sub == "branches":
                cmd_git_branches(_require_project_arg(argv[2:], "usage: panda git branches <project>"))
            elif sub == "add":
                project = _require_project_arg(argv[2:], "usage: panda git add <project> [file ...]")
                files = argv[3:]
                if files == ["--all"]:
                    files = []
                cmd_git_add(project, files)
            elif sub == "commit":
                project = _require_project_arg(argv[2:], "usage: panda git commit <project> <message>")
                cmd_git_commit(project, argv[3:])
            elif sub == "push":
                project = _require_project_arg(argv[2:], "usage: panda git push <project> [remote] [branch]")
                cmd_git_push(project, argv[3:])
            else: _unknown_sub(cmd, sub)


        elif cmd == "py":
            sub = argv[1] if len(argv) > 1 else ""
            if sub == "run":
                script = argv[2] if len(argv) > 2 else ""
                if not script:
                    print("usage: panda py run <script_path> [--timeout N] [--venv PATH] [-- args]")
                    sys.exit(1)
                cmd_py_run(script, argv[3:])
            elif sub == "run-project":
                project = argv[2] if len(argv) > 2 else ""
                script = argv[3] if len(argv) > 3 else ""
                if not project or not script:
                    print("usage: panda py run-project <project> <script_path> [--timeout N] [--venv PATH] [-- args]")
                    sys.exit(1)
                cmd_py_run_project(project, script, argv[4:])
            elif sub == "code":
                code = argv[2] if len(argv) > 2 else ""
                if not code:
                    print("usage: panda py code <code> [--cwd <project|path>] [--timeout N] [--venv PATH]")
                    sys.exit(1)
                cmd_py_code(code, argv[3:])
            else: _unknown_sub(cmd, sub)


        elif cmd == "ssh":
            sub = argv[1] if len(argv) > 1 else ""
            if   sub == "ping":    cmd_ssh_ping()
            elif sub == "status":  cmd_ssh_status()
            elif sub == "disk":    cmd_ssh_disk()
            elif sub == "memory":  cmd_ssh_memory()
            elif sub == "uptime":  cmd_ssh_uptime()
            elif sub == "config":  cmd_ssh_config()
            elif sub == "audit":   cmd_ssh_audit(_parse_lines(argv[2:], default=30))
            elif sub == "nginx":
                action = argv[2] if len(argv) > 2 else ""
                if   action == "status":  cmd_ssh_nginx_status()
                elif action == "restart": cmd_ssh_nginx_restart()
                elif action == "logs":    cmd_ssh_nginx_logs(_parse_lines(argv[3:]))
                else: _unknown_sub("ssh nginx", action)
            elif sub == "service":
                action = argv[2] if len(argv) > 2 else ""
                service = argv[3] if len(argv) > 3 else ""
                if not service:
                    print("usage: panda ssh service <status|restart|logs> <service> [--lines N]")
                    sys.exit(1)
                if   action == "status":  cmd_ssh_service_status(service)
                elif action == "restart": cmd_ssh_service_restart(service)
                elif action == "logs":    cmd_ssh_service_logs(service, _parse_lines(argv[4:]))
                else: _unknown_sub("ssh service", action)
            elif sub == "pm2":
                action = argv[2] if len(argv) > 2 else ""
                if action == "status":
                    cmd_ssh_pm2_status()
                else:
                    name = argv[3] if len(argv) > 3 else ""
                    if not name:
                        print("usage: panda ssh pm2 <logs|restart> <app> [--lines N]")
                        sys.exit(1)
                    if   action == "logs":    cmd_ssh_pm2_logs(name, _parse_lines(argv[4:]))
                    elif action == "restart": cmd_ssh_pm2_restart(name)
                    else: _unknown_sub("ssh pm2", action)
            elif sub == "screen":
                action = argv[2] if len(argv) > 2 else ""
                if action == "list": cmd_ssh_screen_list()
                elif action == "logs":
                    name = argv[3] if len(argv) > 3 else ""
                    if not name:
                        print("usage: panda ssh screen logs <name>")
                        sys.exit(1)
                    cmd_ssh_screen_logs(name)
                else: _unknown_sub("ssh screen", action)
            elif sub == "git":
                action = argv[2] if len(argv) > 2 else ""
                repo = argv[3] if len(argv) > 3 else ""
                if not repo:
                    print("usage: panda ssh git <status|pull> <allowed_repo_path>")
                    sys.exit(1)
                if   action == "status": cmd_ssh_git_status(repo)
                elif action == "pull":   cmd_ssh_git_pull(repo)
                else: _unknown_sub("ssh git", action)
            elif sub == "read-file":
                path = argv[2] if len(argv) > 2 else ""
                if not path:
                    print("usage: panda ssh read-file <remote_path> [--lines N]")
                    sys.exit(1)
                cmd_ssh_read_file(path, _parse_lines(argv[3:], default=500))
            elif sub == "list-dir":
                path = argv[2] if len(argv) > 2 else ""
                if not path:
                    print("usage: panda ssh list-dir <remote_path>")
                    sys.exit(1)
                cmd_ssh_list_dir(path)
            elif sub == "run-alias":
                alias = argv[2] if len(argv) > 2 else ""
                if not alias:
                    print("usage: panda ssh run-alias <alias>")
                    sys.exit(1)
                cmd_ssh_run_alias(alias)
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
