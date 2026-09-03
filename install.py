#!/usr/bin/env python3
"""
Puts the Koovi hooks into the coding tools you use, for every project.

  python3 install.py               every tool found on this machine
  python3 install.py --claude      just Claude Code      (~/.claude/settings.json)
  python3 install.py --codex       just Codex            (~/.codex/hooks.json)
  python3 install.py --cursor      just Cursor           (~/.cursor/hooks.json)
  python3 install.py --uninstall   take them out again

A backup of each file is made before it is changed. Claude Code users can install Koovi as a
plugin instead, and then this script is not needed:  /plugin install koovi@koovi

Only sessions started AFTER installing pick up the hooks, except in Claude Code, which
usually notices straight away.
"""
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parent / "koovi.sh"
COMMAND = {  # what Koovi is asked to do, per event, for each tool
    "claude": {
        "file": Path.home() / ".claude" / "settings.json",
        "events": {"UserPromptSubmit": "prompt", "Stop": "stop", "Notification": "notification",
                   "SubagentStop": "subagent_stop", "SessionEnd": "session_end"},
    },
    "codex": {
        "file": Path.home() / ".codex" / "hooks.json",
        "events": {"UserPromptSubmit": "prompt", "Stop": "stop", "PermissionRequest": "permission",
                   "SubagentStop": "subagent_stop", "SessionEnd": "session_end"},
    },
    "cursor": {
        "file": Path.home() / ".cursor" / "hooks.json",
        "events": {"beforeSubmitPrompt": "prompt", "stop": "stop", "sessionEnd": "session_end"},
    },
}


def is_ours(hook):
    return "koovi" in str(hook.get("command", "")).lower()


def hook_entry(tool, arg):
    """Cursor takes a plain command; Claude Code and Codex take a typed one."""
    command = f"'{LAUNCHER}' {arg}"
    if tool == "cursor":
        return {"command": command, "timeout": 10}
    return {"type": "command", "command": command, "timeout": 10}


def write_hooks(tool, uninstall):
    spec = COMMAND[tool]
    path = spec["file"]
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError as exc:
        print(f"  {tool}: {path} is not valid JSON ({exc}). Fix or move that file, then run this again.")
        return False
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-koovi-{dt.datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(path, backup)
    else:
        backup = None
        path.parent.mkdir(parents=True, exist_ok=True)

    if tool == "cursor":
        settings.setdefault("version", 1)
    hooks = settings.setdefault("hooks", {})
    for event, arg in spec["events"].items():
        if tool == "cursor":
            entries = [h for h in hooks.get(event, []) if not is_ours(h)]
            if not uninstall:
                entries.append(hook_entry(tool, arg))
        else:
            entries = [g for g in hooks.get(event, []) if not any(is_ours(h) for h in g.get("hooks", []))]
            if not uninstall:
                entries.append({"hooks": [hook_entry(tool, arg)]})
        if entries:
            hooks[event] = entries
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
        if tool == "cursor" and set(settings) <= {"version"}:
            settings.pop("version", None)

    path.write_text(json.dumps(settings, indent=2) + "\n")
    json.loads(path.read_text())  # sanity: still valid JSON
    print(f"  {tool}: {'removed from' if uninstall else 'installed in'} {path}"
          + (f"  (backup: {backup.name})" if backup else ""))
    return True


def main():
    uninstall = "--uninstall" in sys.argv
    picked = [t for t in COMMAND if f"--{t}" in sys.argv]
    if not picked:  # nothing named: every tool that is set up on this machine
        picked = [t for t, spec in COMMAND.items() if spec["file"].parent.exists()]
    if not picked:
        print("No coding tool found. Expected one of ~/.claude, ~/.codex or ~/.cursor.")
        return 1

    print(("Removing" if uninstall else "Installing") + " Koovi hooks:")
    ok = all([write_hooks(tool, uninstall) for tool in picked])
    if not uninstall and ok:
        print("Try it now:  ./koovi.sh test done \"Your project\"")
        print("Open windows in Codex and Cursor need a restart. Claude Code usually picks it up at once.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
