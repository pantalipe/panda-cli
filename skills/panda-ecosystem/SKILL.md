---
name: panda-ecosystem
description: Work on the owner's local multi-repository PandaPoints ecosystem. Use when Claude Desktop needs to inspect, modify, test, run, or manage any registered project from gitmanager/projects.json. Use panda-cli as the primary interface for ecosystem operations (git, Python execution, SSH/VPS). Use desktop-commander directly for targeted file reads, log inspection, directory listings, and file searches when it is more token-efficient than going through panda-cli.
---

# Panda Ecosystem

Use this skill for work across the local PandaPoints ecosystem.

## Tool Roles

**panda-cli is the primary interface for ecosystem operations.** Use it for all Git, Python execution, SSH, VPS, and project-registry operations. It provides consistent output formatting, venv detection, timeout handling, and allowlist safety for remote commands.

**desktop-commander is both the terminal layer AND a direct file/process toolkit.** Use it to invoke panda-cli via `start_process`, but also use its native tools directly when that is more token-efficient. See the decision table below.

**Do not use desktop-commander tools to replicate what panda-cli already covers well** (e.g., don't use `read_file` to parse a git diff when `panda git diff` is available — but do use `read_file` with offset/length to inspect a specific section of a source file).

---

## Decision Table: panda-cli vs desktop-commander

| Task | Preferred tool |
|------|---------------|
| Git status / diff / log / branches | `panda git …` |
| Run Python script or inline code | `panda py …` |
| SSH / VPS / pm2 / nginx | `panda ssh …` |
| Project registry lookup | `panda projects …` |
| Read a full small file (<100 lines) | `desktop-commander:read_file` |
| Read specific lines of a large file | **`desktop-commander:read_file` with `offset` + `length`** |
| Tail end of a log or JSON | **`desktop-commander:read_file` with negative `offset`** |
| List directory tree | **`desktop-commander:list_directory` with `depth`** |
| Get file size / modified date | **`desktop-commander:get_file_info`** |
| Search text/code across files | **`desktop-commander:start_search`** |
| Read paginated terminal output | **`desktop-commander:read_process_output`** |
| Surgical text replacement in a file | **`desktop-commander:edit_block`** |
| Write a new file | **`desktop-commander:write_file`** |
| Start a background process | `desktop-commander:start_process` |

**Rule of thumb:** if panda-cli produces the answer in one call with clean output → use it. If getting the answer requires reading N lines of a file, tailing a log, or searching a section, use desktop-commander directly to avoid loading the whole file into context.

---

## desktop-commander Efficiency Patterns

### Read specific lines of a file
```
desktop-commander:read_file
  path: "<project_path>/some_file.py"
  offset: 40      # start at line 40 (0-based)
  length: 30      # read 30 lines only
```

### Tail the end of a log or JSON
```
desktop-commander:read_file
  path: "<project_path>/data/price_history.json"
  offset: -20     # last 20 lines (Unix tail behavior)
```

### Directory tree with controlled depth
```
desktop-commander:list_directory
  path: "<project_path>"
  depth: 2        # avoid flooding context with node_modules etc.
```

### File metadata without reading content
```
desktop-commander:get_file_info
  path: "<project_path>/data/some_file.json"
# Returns: size, modified date, type — no file content loaded
```

### Search across source files
```
desktop-commander:start_search
  path: "<project_path>"
  pattern: "useEffect"
  includePattern: "*.tsx"
# Returns matched lines with file paths; use get_more_search_results to paginate
```

### Read paginated terminal output
```
desktop-commander:read_process_output
  pid: <pid from start_process>
  offset: 0
  length: 100
# Prevents context overflow on verbose commands
```

### Surgical file edit
```
desktop-commander:edit_block
  file_path: "<project_path>/src/file.ts"
  old_string: "exact text to replace"
  new_string: "replacement text"
```

---

## Standard panda-cli Pattern

For every ecosystem operation, the standard invocation is:

```
desktop-commander:start_process
  command: "python <panda_cli_path>/panda.py <command>"
```

> Tip: on the owner's machine, `panda.bat` at the repo root wraps this call — use `panda <command>` if the wrapper is on PATH.

### Projects

```powershell
panda projects list                        # list all registered projects
panda projects show <project>              # metadata for a project
panda projects path <project>              # resolve absolute path
panda projects status                      # same as git ecosystem-status
```

### Git

```powershell
panda git ecosystem-status                 # Git health summary for all projects
panda git status <project>                 # git status --short --branch
panda git diff <project> [file]            # unstaged diff
panda git diff-staged <project>            # staged diff
panda git log <project> [--limit N]        # recent commits
panda git branches <project>               # local branches
panda git add <project> [file ...|--all]   # stage specific files or all changes
panda git commit <project> "<message>"     # commit staged changes
panda git push <project> [remote] [branch] # push committed changes
```

**Git workflow order:** `git add` → `git diff-staged` (review) → `git commit` → `git push`

### Python

```powershell
panda py run <script_path>                        # run a Python script
panda py run-project <project> <script>           # run script inside project venv
panda py code "print('ok')" --cwd <project>       # run inline Python code
```

### LLM (llama-swap)

```powershell
panda llm start        # start llama-swap on :8080
panda llm stop         # stop llama-swap
panda llm status       # health check + list loaded models
```

### Services

```powershell
panda dapp dev                    # Next.js dev server (port 3000)
panda dapp poller                 # price_poller.py --local
panda dapp backfill               # backfill.py --local (blocking)
panda rotman server               # rotman web UI
panda rotman generate <channel>   # run content pipeline (blocking)
panda gitmanager                  # gitmanager server (port 8765)
panda conduler                    # conduler server (port 7071)
panda bench run                   # ollama-bench (blocking)
panda status                      # table of tracked services + PIDs
panda stop                        # kill all tracked services
```

### SSH (controlled VPS operations)

```powershell
panda ssh ping                              # VPS connectivity check
panda ssh status                            # pm2 + disk + memory
panda ssh config                            # show SSH config (no secrets)
panda ssh audit [--lines N]                 # local audit log
panda ssh nginx <status|restart|logs>       # nginx operations
panda ssh pm2 <status|logs|restart>         # pm2 operations
panda ssh git <status|pull> <repo_path>     # remote git operations
panda ssh read-file <remote_path>           # read first lines of remote file
panda ssh list-dir <remote_path>            # list remote directory
panda ssh run-alias <alias>                 # run pre-approved command alias
```

### VPS (higher-level shortcuts)

```powershell
panda vps ssh                               # open interactive SSH session
panda vps status                            # pm2 + disk + memory overview
panda vps logs <pp|telegramBot>             # tail logs for dapp or bot
panda vps restart <pp|telegramBot>          # pm2 restart an app
panda vps deploy <pp>                       # git pull + pm2 restart
panda vps send <local_path> <remote_path>   # scp a file to the VPS
```

---

## Source of Truth

- Treat `gitmanager/projects.json` as the project registry.
- Prefer registered project names over hardcoded paths.
- Do not scan the entire home directory unless the registry is missing or the user asks.

---

## Context Efficiency

- Use `read_file` with `offset`/`length` rather than reading entire files when only a section is needed.
- Use `get_file_info` to check file size before deciding to read it in full.
- Use `list_directory` with `depth: 1` or `depth: 2`; avoid unlimited recursion.
- Batch related inspections before proposing edits.
- Summarize findings instead of repeatedly reopening the same files.
- Avoid reading: `node_modules`, `dist`, `build`, `coverage`, `.next`, `out`, `tmp`, `logs` (unless explicitly requested).

---

## Safety Rules

- Ask before `git push`, `git reset`, `git rebase`, recursive deletion, deploys, and VPS restarts.
- Do not use arbitrary SSH for normal VPS operations — prefer `panda ssh` commands.
- Ask before `panda ssh pm2 restart`, `panda ssh nginx restart`, `panda ssh git pull`, or any deploy-like command.
- Use `panda ssh config` to inspect allowlists; `panda ssh audit --lines 50` to inspect recent remote actions.
- If `panda ssh` authentication fails, check `PANDA_SSH_KEY_PASSPHRASE` or ssh-agent availability.
- Preserve user changes — check status before edits; do not revert unrelated files.
- Keep changes scoped to the requested project unless cross-project migration is explicitly requested.

---

## Typical Workflow

1. Look up the project with `panda projects show <project>`.
2. Inspect git status with `panda git status <project>`.
3. Use `desktop-commander:get_file_info` or `read_file` with offset/length to read only what is needed.
4. Use `desktop-commander:start_search` to locate relevant code before opening files.
5. Make scoped edits via `desktop-commander:edit_block`.
6. Run targeted tests or smoke checks with `panda py run`.
7. Summarize changed files, validation results, and any follow-up risk.
