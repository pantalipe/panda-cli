---
name: panda-ecosystem
description: Work on Felipe Panta's local multi-repository PandaPoints ecosystem in workspace_root<. Use when Codex needs to inspect, modify, test, run, or manage any registered project from gitmanager/projects.json; use panda-cli for project lookup, Git operations, Python script execution, local services, and controlled VPS operations.
---

# Panda Ecosystem

Use this skill for work across the local PandaPoints ecosystem.

## Source of Truth

- Treat `workspace_root</gitmanager/projects.json` as the project registry.
- Prefer registered project names over hardcoded paths.
- Use `PROJECTS_JSON` only when the user explicitly asks to test another registry.
- Do not scan all of `workspace_root<` unless the registry is missing or the user asks for it.

## CLI First

Prefer `workspace_root</panda-cli/panda.py` through the `panda` wrapper when available.
If the wrapper is not available, run `python workspace_root</panda-cli/panda.py ...`.

Core commands:

```powershell
panda projects list
panda projects show <project>
panda projects path <project>
panda projects status
panda git ecosystem-status
panda git status <project>
panda git diff <project> [file]
panda git diff-staged <project>
panda git log <project> --limit 10
panda git branches <project>
panda py run <script_path> --timeout 60
panda py run-project <project> <script_path> --timeout 60
panda py code "print('ok')" --cwd <project>
panda ssh config
panda ssh audit --lines 50
panda ssh pm2 status
panda ssh pm2 logs pp --lines 50
panda ssh nginx status
panda ssh git status remote_project_path<
```

For Python execution, prefer `panda py` so venv detection, timeout, stdout, stderr, and exit code formatting stay consistent.

## Safety Rules

- Ask before `git push`, `git reset`, `git rebase`, recursive deletion, deploys, and VPS restarts.
- Do not use arbitrary SSH for normal VPS operations. Prefer controlled `panda ssh` commands.
- Ask before `panda ssh pm2 restart`, `panda ssh nginx restart`, `panda ssh service restart`, `panda ssh git pull`, or any deploy-like command.
- Use `panda ssh config` to inspect allowlists and `panda ssh audit --lines 50` to inspect recent remote actions.
- If `panda ssh` authentication fails, check whether `ssh_passphrase_env<`/`ssh_passphrase_env<` is configured or whether the key is available to `ssh.exe`/ssh-agent.
- Preserve user changes. Check status before edits and do not revert unrelated files.
- Keep changes scoped to the requested project unless cross-project migration is explicitly requested.

## Typical Workflow

1. Read the relevant project entry with `panda projects show <project>`.
2. Inspect status with `panda git status <project>`.
3. Read only the files needed for the requested task.
4. Make scoped edits.
5. Run the narrowest useful tests or smoke checks.
6. Summarize changed files, validation, and any follow-up risk.
