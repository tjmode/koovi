#!/usr/bin/env python3
"""
Koovi - a small add-on that SPEAKS which session finished or needs you.

Claude Code, Codex and Cursor all call this program through their hooks. Koovi
only listens and speaks. It never talks back, and never touches your code.
In quiet mode (config: mode: quiet) it shows a screen light instead of talking.

Commands used by the hooks (they read a JSON payload on stdin):
  koovi.py prompt         you sent a message          (UserPromptSubmit)
  koovi.py stop           Claude finished a turn      (Stop)
  koovi.py notification   Claude is asking or waiting (Notification)
  koovi.py permission     a tool needs your approval  (Codex PermissionRequest)
  koovi.py session_end    a session was closed        (SessionEnd)
  koovi.py subagent_stop  a subagent finished         (SubagentStop, diary only)

Commands for you (the /koovi:koovi command in Claude Code runs these too):
  koovi.py status          version, mode, screen light, muted projects, last decisions
  koovi.py settings [--json]  the main switches: on/off, how it reaches you, calls, research, quiet hours
  koovi.py voice|quiet|auto   switch how it reaches you: talk, screen light only, or talk only on headphones
  koovi.py mute [folder]   silence one project (default: the folder you are in);  unmute to undo
  koovi.py set KEY VALUE   change any setting, e.g. set user boss, set rate 190, set light.enabled false
  koovi.py test [done|also_done|asking|permission|reminder] [Project] [question...]   hear a sample line
  koovi.py log [N]        show the last N log lines (default 30)
  koovi.py doctor         check that everything is in place
  koovi.py mic            is any app using the microphone right now?
  koovi.py voices         list the English voices on this Mac
  koovi.py voice NAME     switch to that voice and play a sample
  koovi.py light          what the screen light shows right now (and the current mode)
  koovi.py light test     show a demo flash
  koovi.py light off      clear the screen light
  koovi.py menu [show|hide|login on|login off]   the Koovi icon in the macOS menu bar
"""

import contextlib
import datetime as dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:  # file locking has a different name on Windows
    import fcntl
    msvcrt = None
except ImportError:
    fcntl = None
    import msvcrt

KOOVI_VERSION = "1.0.0"

MAC, WINDOWS, LINUX = "mac", "windows", "linux"
OS = MAC if sys.platform == "darwin" else (WINDOWS if os.name == "nt" else LINUX)

HERE = Path(__file__).resolve().parent
STATE_DIR = Path.home() / ".koovi"
CONFIG_PATH = STATE_DIR / "config.yaml"           # your settings; created from the example on first use
EXAMPLE_CONFIG = HERE / "config.example.yaml"     # shipped with Koovi
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE = STATE_DIR / "koovi.log"
SPEECH_LOCK = STATE_DIR / "speech.lock"
STATE_LOCK = STATE_DIR / "state.lock"
CONFIG_LOCK = STATE_DIR / "config.lock"           # one writer of config.yaml at a time
LIGHT_FILE = STATE_DIR / "light.json"             # what the screen light shows right now
CALL_FILE = STATE_DIR / "call.json"               # the last call app seen using the microphone
BACKGROUND_FILE = STATE_DIR / "background.jsonl"  # raw background tasks of the last "done"s said while work still ran
LIGHT_SRC = HERE / "light" / "KooviLight.swift"
LIGHT_BIN = HERE / "light" / "koovi-light"       # helper shipped with Koovi (macOS)
LIGHT_BUILT = STATE_DIR / "bin" / "koovi-light"  # helper built here if the shipped one cannot run
LIGHT_PS1 = HERE / "light" / "KooviLight.ps1"    # the same idea for Windows
BIN_DIR = STATE_DIR / "bin"
SHIM = BIN_DIR / "koovi"                         # always runs the Koovi that is installed now; the menu calls this
MENU_SRC = HERE / "menu" / "KooviMenu.swift"
MENU_BIN = HERE / "menu" / "koovi-menu"          # the menu bar icon, shipped with Koovi (macOS)
MENU_LOCK = STATE_DIR / "menu.lock"              # held by the running menu, with its pid inside
LOGIN_ITEM = Path.home() / "Library" / "LaunchAgents" / "com.tjmode.koovi.menu.plist"

DEFAULTS = {
    "enabled": True,  # false: Koovi still keeps track of your sessions, but never speaks or flashes
    "assistant": "Koovi",
    "user": "boss",
    "voice": "Samantha",
    "rate": 175,
    "chime": "/System/Library/Sounds/Glass.aiff",
    "focus_check": True,
    "permission_always_speak": True,
    "always_announce_questions": True,
    "question_words": 8,  # how much of the question to read out. A line should be over in about three seconds.
    "wait_for_background_tasks": False,  # only for people whose background work always wakes the session quickly
    "wait_for_agents": True,  # research agents always finish and wake the session, so their pause is not "done"
    "remind_for": ["asking", "permission"],
    "menu_bar": True,  # macOS: the Koovi icon in the menu bar. "Hide from menu bar" sets this to false
    "mode": "voice",  # voice | quiet (screen light only) | auto (voice on headphones, light on speakers)
    "light": {
        "enabled": True,
        "when": "instead_of_voice",  # or "always"
        "corner": "top-right",
        "pulse": True,
        "seconds": 5,  # how long one flash lasts; then the same reminder ladder as the voice
        "colors": {"done": "#ff3b30", "also_done": "#ff3b30", "asking": "#ff9f0a", "permission": "#ff9f0a",
                   "reminder": "#ff9f0a"},
        "labels": {"done": "done", "also_done": "done", "asking": "needs an answer", "permission": "wants permission",
                   "reminder": "still waiting"},
    },
    "music_duck": True,
    "music_duck_percent": 20,
    "wait_for_mic": True,
    "mic_wait_max_seconds": 120,
    "mic_settle_seconds": 1.5,
    "mic_ignore_apps": [],  # apps that keep the mic open all day without a person talking (bundle id or name)
    "call_grace_seconds": 600,  # a call app seen on the mic still counts this long while it plays sound (muted calls)
    "browser_music_sites": ["youtube.com", "soundcloud.com", "open.spotify.com", "music.apple.com"],
    "browser_pause": True,  # pause browser videos and music while Koovi talks, so you miss nothing; false turns them down
    "quiet_hours": {"start": None, "end": None},
    "timing": {
        "min_task_seconds": 5,
        "chat_needs_seconds": 120,
        "reminder_after_seconds": 120,
        "reminders": 1,
        "debounce_seconds": 20,
        "also_done_window_seconds": 30,
    },
    "projects": {},
    "phrases": {
        "done": ["{project} is done, {user}.", "{user}, {project} is done."],
        "also_done": ["{project} is also done."],
        "asking": ["{project} asks: {question}", "{user}, {project} needs you."],
        "permission": ["{project} needs a yes, {user}."],
        "reminder": ["{project} again: {question}", "{user}, {project} is still waiting."],
    },
}

ENV_TIMING = {
    "min_task_seconds": "JARVIS_MIN_TASK_SECONDS",
    "chat_needs_seconds": "JARVIS_CHAT_NEEDS_SECONDS",
    "reminder_after_seconds": "JARVIS_REMINDER_AFTER_SECONDS",
    "reminders": "JARVIS_REMINDERS",
    "debounce_seconds": "JARVIS_DEBOUNCE_SECONDS",
    "also_done_window_seconds": "JARVIS_ALSO_DONE_WINDOW_SECONDS",
}


# ----------------------------------------------------------------------------- config

def _strip_comment(line):
    """Drop a trailing # comment, but not a # inside quotes."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _split_flow(body):
    """Split 'a, b, [c, d], {e: f}' on the commas that are not inside quotes or brackets."""
    parts, depth, quote, cur = [], 0, None, ""
    for ch in body:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur += ch
        elif ch in "[{":
            depth += 1
            cur += ch
        elif ch in "]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return [x.strip() for x in parts]


def _split_key(text):
    """'key: value' -> (key, value). The key may contain spaces; a colon inside quotes does not count."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == ":" and (i + 1 == len(text) or text[i + 1] in " \t"):
            return text[:i].strip().strip("\"'"), text[i + 1:].strip()
    return None, text


def _scalar(text):
    """One YAML value: quoted string, number, true/false, empty, [list] or {map}."""
    text = text.strip()
    if text == "" or text in ("~", "null"):
        return None
    if text[0] == text[-1] and text[0] in "\"'" and len(text) >= 2:
        inner = text[1:-1]
        return inner.replace('\\"', '"') if text[0] == '"' else inner.replace("''", "'")
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(x) for x in _split_flow(text[1:-1])]
    if text.startswith("{") and text.endswith("}"):
        out = {}
        for item in _split_flow(text[1:-1]):
            k, v = _split_key(item)
            if k is not None:
                out[k] = _scalar(v)
        return out
    low = text.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_yaml(text):
    """Read the small YAML that config.yaml uses: nested maps, '- ' lists, [flow] lists, {flow} maps, comments.
    That is all Koovi needs, so nobody has to install PyYAML."""
    rows = []
    for raw in str(text or "").splitlines():
        line = _strip_comment(raw.expandtabs(4)).rstrip()
        if line.strip():
            rows.append((len(line) - len(line.lstrip(" ")), line.strip()))

    def block(i, indent):
        is_list = rows[i][1].startswith("- ") or rows[i][1] == "-"
        out = [] if is_list else {}
        while i < len(rows) and rows[i][0] == indent:
            ind, text = rows[i]
            if is_list:
                if not (text.startswith("- ") or text == "-"):
                    break
                out.append(_scalar(text[1:]))
                i += 1
                continue
            key, rest = _split_key(text)
            if key is None:
                raise ValueError(f"cannot read line: {text!r}")
            i += 1
            if rest == "" and i < len(rows) and rows[i][0] > indent:
                out[key], i = block(i, rows[i][0])
            else:
                out[key] = _scalar(rest)
        return out, i

    if not rows:
        return {}
    value, i = block(0, rows[0][0])
    if i < len(rows):
        raise ValueError(f"cannot read line: {rows[i][1]!r}")
    return value


def ensure_config():
    """Make sure your settings file exists; on first use it is a copy of the example that ships with Koovi."""
    STATE_DIR.mkdir(exist_ok=True)
    if not CONFIG_PATH.exists() and EXAMPLE_CONFIG.exists():
        CONFIG_PATH.write_text(EXAMPLE_CONFIG.read_text())
        log("config", "-", f"created {CONFIG_PATH} from the example")
    return CONFIG_PATH


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        user = parse_yaml(ensure_config().read_text())
        if not isinstance(user, dict):
            user = {}
    except FileNotFoundError:
        user = {}
    except Exception as exc:  # bad file: keep defaults, say why
        log("config", "-", f"ERROR reading {CONFIG_PATH}: {exc}")
        user = {}
    for key, val in user.items():
        if val is None:
            continue  # a heading with nothing under it, like "projects:", means "leave it alone"
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    for key, env in ENV_TIMING.items():
        if os.environ.get(env):
            cfg["timing"][key] = float(os.environ[env])
    if os.environ.get("JARVIS_FOCUS_CHECK") in ("0", "false", "no"):
        cfg["focus_check"] = False
    return cfg


# Claude Desktop runs chats without a project in folders like scratch-2026-11-11-47c6d0. Read out
# loud that is a date and a code, so such a chat is called by its name, or simply "scratch chat".
SCRATCH_FOLDER = re.compile(r"^scratch-\d{4}-\d{2}-\d{2}-[0-9a-f]+$", re.I)


def project_settings(cfg, folder, rename=""):
    entry = (cfg.get("projects") or {}).get(folder) or {}
    if isinstance(entry, str):
        entry = {"say": entry}
    say = entry.get("say")
    if not say and SCRATCH_FOLDER.match(folder):
        say = short_title(rename or "", max_words=4) or "scratch chat"
    say = say or folder.replace("-", " ").replace("_", " ")
    return {"say": say, "mute": bool(entry.get("mute", False))}


def in_quiet_hours(cfg):
    q = cfg.get("quiet_hours") or {}
    start, end = q.get("start"), q.get("end")
    if not start or not end:
        return False
    now = dt.datetime.now().time()
    s = dt.time(*map(int, str(start).split(":")))
    e = dt.time(*map(int, str(end).split(":")))
    if s <= e:
        return s <= now < e
    return now >= s or now < e  # wraps past midnight


# ----------------------------------------------------------------------------- state & log

LOG_MAX_BYTES = 1_000_000
LOG_KEEP_LINES = 3000


def atomic_write(path, text):
    """Write the whole file, then swap it into place, so a crash never leaves it half written."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")  # two writers never share a temp file
    tmp.write_text(text)
    os.replace(tmp, path)


def log(event, project, decision, **extra):
    STATE_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tail = " ".join(f"{k}={v}" for k, v in extra.items() if v not in (None, ""))
    with open(LOG_FILE, "a") as f:
        f.write(f"{stamp} | {event:<12} | {project:<16} | {decision} {tail}".rstrip() + "\n")
    if LOG_FILE.stat().st_size > LOG_MAX_BYTES:  # keep the diary from growing forever
        atomic_write(LOG_FILE, "\n".join(LOG_FILE.read_text(errors="replace").splitlines()[-LOG_KEEP_LINES:]) + "\n")


@contextlib.contextmanager
def locked_state():
    with one_at_a_time(STATE_LOCK):
        try:
            st = json.loads(STATE_FILE.read_text())
        except Exception:
            st = {}
        st.setdefault("sessions", {})
        try:
            yield st
        finally:
            cutoff = time.time() - 2 * 24 * 3600
            st["sessions"] = {k: v for k, v in st["sessions"].items()
                              if v.get("last_seen", 0) > cutoff}
            atomic_write(STATE_FILE, json.dumps(st, indent=1))


# ----------------------------------------------------------------------------- transcript

def _blocks(entry):
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [b for b in (content or []) if isinstance(b, dict)]


def _parse_ts(ts):
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def read_tail(path, limit=1_000_000):
    """The last part of a big file, whole lines only. The last turn is all Koovi ever needs."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - limit))
        data = f.read()
    if size > limit:
        data = data.split(b"\n", 1)[-1]
    return data.decode("utf-8", errors="replace")


def read_entry(e):
    """One transcript line from Claude Code or Codex, as (who, text, when, [(tool name, tool input)]).
    None for lines Koovi does not care about, so the rest of the reading works the same for every tool."""
    when = _parse_ts(e.get("timestamp"))
    kind = e.get("type")
    if kind in ("user", "assistant") and isinstance(e.get("message"), dict):        # Claude Code
        if e.get("isSidechain"):
            return None
        blocks = _blocks(e)
        if kind == "user" and ("toolUseResult" in e or any(b.get("type") == "tool_result" for b in blocks)):
            return None  # a tool answering itself, not you typing
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        tools = [(b.get("name"), b.get("input") or {}) for b in blocks if b.get("type") == "tool_use"]
        return kind, text, when, tools
    if kind == "response_item" and isinstance(e.get("payload"), dict):              # Codex
        item = e["payload"]
        if item.get("type") == "function_call":
            return "assistant", "", when, [(item.get("name"), item.get("arguments") or {})]
        if item.get("type") == "message" and item.get("role") in ("user", "assistant"):
            text = "\n".join(c.get("text", "") for c in (item.get("content") or [])
                             if isinstance(c, dict) and c.get("text"))
            return item["role"], text, when, []
    return None


def analyze_transcript(path):
    """Look only at the last turn: when did you last type, how many tools ran, did it end in a question."""
    info = {"last_user_ts": None, "tool_uses": 0, "is_question": False, "last_user_text": "", "question": "",
            "ask_tool": False, "readable": False}
    if not path:
        return info
    try:
        lines = read_tail(Path(path)).splitlines()
    except OSError:
        return info
    assistant = []  # newest first
    for line in reversed(lines):
        try:
            entry = read_entry(json.loads(line))
        except Exception:
            continue
        if not entry:
            continue
        info["readable"] = True
        who, text, when, tools = entry
        if who == "assistant":
            assistant.append((text, tools))
        else:
            info["last_user_ts"] = when
            info["last_user_text"] = text
            break
    for _, tools in assistant:
        for name, tool_input in tools:
            info["tool_uses"] += 1
            if name == "AskUserQuestion":
                info["is_question"] = info["ask_tool"] = True
                asked = (tool_input or {}).get("questions") or []
                if asked and not info["question"]:
                    info["question"] = question_snippet(asked[0].get("question", ""), whole=True)
    for text, _ in assistant:  # newest entry that has visible text
        if text.strip():
            is_q, q = question_from_text(text)
            if is_q:
                info["is_question"] = True
                info["question"] = info["question"] or q
            break
    return info


def question_from_text(text):
    """Does this reply end by asking you something? Returns (yes/no, the question trimmed for speech)."""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    if not lines or not lines[-1].endswith("?"):
        return False, ""
    return True, question_snippet(text)


def question_snippet(text, max_words=18, whole=False):
    """The question Claude asked, trimmed for speech: the last sentence ending in '?', without markdown or code."""
    text = re.sub(r"```.*?```", " ", str(text or ""), flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+?(?=[.,;:!?]*(?:\s|$))", "link", text)  # keep the sentence's own punctuation
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not whole:
        parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text)]
        asked = [s for s in parts if s.endswith("?")]
        if not asked:
            return ""
        text = asked[-1]
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words]).rstrip(",;:.") + "?"
    return text


def session_rename(path):
    """Your own /rename for the session, if you gave one. Automatic titles go stale, so they are ignored."""
    if not path:
        return ""
    try:
        lines = read_tail(Path(path)).splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if "custom-title" not in line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "custom-title":
            title = next((str(v) for k, v in e.items() if k.lower().endswith("title") and k != "type" and isinstance(v, str)), "")
            if title.strip():
                return title.strip()
    return ""


def is_system_notice(text):
    """True for text Claude Code injects itself (a background task notice, a system reminder), not something you typed."""
    return str(text or "").lstrip().startswith("<")


def short_title(title, max_words=6):
    words = title.replace("_", " ").replace("-", " ").split()
    return " ".join(words[:max_words])


def spoken_with_session(st, s, sid, folder, spoken, now):
    """If another live window uses the same folder, say which one.

    Only a name you chose with /rename is spoken. Anything scraped out of your own words
    reads as nonsense out loud, so the others are counted instead."""
    active = [(k, v) for k, v in st["sessions"].items()
              if v.get("folder") == folder and not v.get("ended") and now - v.get("last_seen", 0) < 8 * 3600]
    if len(active) < 2:
        return spoken
    label = short_title(s.get("rename") or "", max_words=3)
    if label and label.lower() in spoken.lower():
        label = ""  # the name is already what is spoken (a scratch chat), so count instead of saying it twice
    if label:
        return f"{spoken}, {label}"
    active.sort(key=lambda kv: kv[1].get("first_seen", 0))
    n = next((i + 1 for i, (k, _) in enumerate(active) if k == sid), 0)
    return f"{spoken}, session {n}" if n else spoken


# ----------------------------------------------------------------------------- focus, speech

FRONT_SCRIPT = '''
tell application "System Events"
  set p to first application process whose frontmost is true
  set n to name of p
  set t to ""
  try
    set t to name of front window of p
  end try
end tell
return n & "|||" & t
'''


WINDOWS_FRONT = ("Add-Type -Name W -Namespace K -MemberDefinition '"
                 "[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow();"
                 "[DllImport(\"user32.dll\")] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int c);"
                 "[DllImport(\"user32.dll\")] public static extern int GetWindowThreadProcessId(IntPtr h, out int p);';"
                 "$h = [K.W]::GetForegroundWindow(); $b = New-Object System.Text.StringBuilder 512;"
                 "[void][K.W]::GetWindowText($h, $b, 512); $p = 0; [void][K.W]::GetWindowThreadProcessId($h, [ref]$p);"
                 "$n = (Get-Process -Id $p -ErrorAction SilentlyContinue).ProcessName;"
                 "Write-Output \"$n|||$($b.ToString())\"")


def front_window_command():
    """How to ask this machine which window is in front. None where we cannot tell."""
    if OS == MAC:
        return ["osascript", "-e", FRONT_SCRIPT]
    if OS == WINDOWS:
        return PS + [WINDOWS_FRONT]
    if shutil.which("xdotool"):
        return ["sh", "-c", 'printf "%s|||%s" "$(xdotool getactivewindow getwindowclassname 2>/dev/null)" '
                            '"$(xdotool getactivewindow getwindowname 2>/dev/null)"']
    return None


def front_window():
    command = front_window_command()
    if not command:
        return "", ""
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=6)
        if r.returncode != 0:
            return "", ""
        app, _, title = r.stdout.strip().partition("|||")
        return app.strip(), title.strip()
    except Exception:
        return "", ""


def is_focused(folder):
    """True when the window you are typing in belongs to this project folder."""
    app, title = front_window()
    if not title:
        return False, app, title
    return folder.lower() in title.lower(), app, title


PLAYERS = ("Music", "Spotify")


def _osa(script, timeout=3):
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else None


def duck_music(cfg):
    if OS != MAC:
        return None  # turning other apps down is a Mac trick for now
    """Turn a playing music app down while Koovi talks. Returns what to put back afterwards."""
    if not cfg.get("music_duck", True):
        return []
    level = int(cfg.get("music_duck_percent", 20))
    saved = []
    for app in PLAYERS:
        if subprocess.run(["pgrep", "-xq", app]).returncode != 0:
            continue  # not running: never launch it
        try:
            if _osa(f'tell application "{app}" to get player state') != "playing":
                continue
            vol = int(float(_osa(f'tell application "{app}" to get sound volume') or 0))
            if vol > level:
                _osa(f'tell application "{app}" to set sound volume to {level}')
                saved.append((app, vol))
                log("music", app, f"turned down from {vol}% to {level}%")
        except Exception:
            pass
    return saved


BROWSERS = {"Brave Browser": "chromium", "Google Chrome": "chromium", "Safari": "safari"}
BROWSER_SETTING_HINT = {"chromium": "View > Developer > Allow JavaScript from Apple Events",
                        "safari": "Develop > Allow JavaScript from Apple Events"}
JS_DUCK = ("(function(){var n=0,L=%s,ms=document.querySelectorAll('video,audio');"
           "for(var i=0;i<ms.length;i++){var m=ms[i];if(!m.paused&&!m.muted&&(m.volume>L||m.dataset.kooviVol)){"
           "if(!m.dataset.kooviVol){m.dataset.kooviVol=m.volume;}m.volume=L;n++;}}return n;})()")
# Pausing keeps your place in a video; turning it down lets it run on while Koovi talks over it.
JS_PAUSE = ("(function(){var n=0,ms=document.querySelectorAll('video,audio');"
            "for(var i=0;i<ms.length;i++){var m=ms[i];if(!m.paused&&!m.muted){"
            "m.dataset.kooviPaused=Date.now();m.pause();n++;}}return n;})()")
# Puts back both kinds, so a tab heals whichever way it was quietened. A tab paused more than ten
# minutes ago is left alone: sound starting out of nowhere is worse than a video left paused.
JS_RESTORE = ("(function(){var n=0,ms=document.querySelectorAll('video,audio');"
              "for(var i=0;i<ms.length;i++){var m=ms[i];if(m.dataset.kooviVol){"
              "m.volume=parseFloat(m.dataset.kooviVol);delete m.dataset.kooviVol;n++;}"
              "if(m.dataset.kooviPaused){var t=parseFloat(m.dataset.kooviPaused);delete m.dataset.kooviPaused;"
              "if(m.paused&&Date.now()-t<600000){var p=m.play();if(p&&p.catch){p.catch(function(){});}n++;}}}"
              "return n;})()")


def _browser_script(app, flavor):
    run_js = "execute t javascript js" if flavor == "chromium" else "do JavaScript js in t"
    return f"""on run argv
  set js to item 1 of argv
  set sites to items 2 thru -1 of argv
  set n to 0
  tell application "{app}"
    repeat with w in windows
      repeat with t in tabs of w
        set u to ""
        try
          set u to URL of t
        end try
        if u is missing value then set u to ""
        repeat with s in sites
          if u contains s then
            try
              set r to ({run_js})
              set n to n + (r as integer)
            on error errMsg
              return "ERR " & errMsg
            end try
            exit repeat
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return n as text
end run"""


def _running_browsers():
    if OS != MAC:
        return  # turning browser tabs down is a Mac trick for now
    for app, flavor in BROWSERS.items():
        if Path(f"/Applications/{app}.app").exists() and subprocess.run(["pgrep", "-xq", app]).returncode == 0:
            yield app, flavor


def _run_browser_js(app, flavor, js, sites):
    """Returns ('ok', count) or ('off', hint) or ('err', message)."""
    try:
        r = subprocess.run(["osascript", "-", js, *sites], input=_browser_script(app, flavor),
                           capture_output=True, text=True, timeout=8)
    except Exception as exc:
        return "err", str(exc)
    out = (r.stdout.strip() or r.stderr.strip())
    if out.startswith("ERR") or r.returncode != 0:
        if "turned off" in out or "Apple Events" in out or "not allowed" in out:
            return "off", BROWSER_SETTING_HINT[flavor]
        return "err", out[:120]
    try:
        return "ok", int(out)
    except ValueError:
        return "err", out[:120]


def duck_browsers(cfg):
    if OS != MAC:
        return []
    """Turn down playing videos/music in browser tabs (YouTube etc). Returns the browsers to restore."""
    if not cfg.get("music_duck", True):
        return []
    sites = [str(x) for x in (cfg.get("browser_music_sites") or [])]
    if not sites:
        return []
    level = max(0.0, min(1.0, int(cfg.get("music_duck_percent", 20)) / 100.0))
    pause = cfg.get("browser_pause", True)
    js = JS_PAUSE if pause else JS_DUCK % level
    ducked = []
    for app, flavor in _running_browsers():
        status, info = _run_browser_js(app, flavor, js, sites)
        if status == "ok" and info > 0:
            ducked.append((app, flavor))
            log("music", app, f"paused {info} playing tab(s)" if pause
                else f"turned down {info} playing tab(s) to {int(level * 100)}%")
        elif status == "off":
            log("music", app, f"cannot {'pause' if pause else 'turn down'} browser music: switch on {info}")
        elif status == "err":
            log("music", app, f"browser check failed: {info}")
    return ducked


def restore_browsers(cfg, ducked):
    """Put browser volumes back. Runs on every open browser, so a tab left quiet by an earlier failure heals too."""
    if not cfg.get("music_duck", True):
        return
    sites = [str(x) for x in (cfg.get("browser_music_sites") or [])]
    if not sites:
        return
    for app, flavor in _running_browsers():
        status, info = _run_browser_js(app, flavor, JS_RESTORE, sites)
        if status == "ok" and info > 0:
            log("music", app, f"put {info} tab(s) back as they were")
        elif status == "err":
            log("music", app, f"could not put the browser music back: {info}")


def restore_music(saved):
    for app, vol in saved:
        try:
            _osa(f'tell application "{app}" to set sound volume to {vol}')
        except Exception:
            pass


# ---- microphone: never talk while you are dictating or on a call

def _fourcc(code):
    return int.from_bytes(code.encode(), "big")


def _core_audio():
    """CoreAudio and its property address, loaded once. Raises where there is no CoreAudio."""
    global _CA
    if _CA is None:
        import ctypes
        import ctypes.util

        class Addr(ctypes.Structure):
            _fields_ = [("sel", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("elem", ctypes.c_uint32)]

        _CA = (ctypes, ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreAudio")), Addr)
    return _CA


_CA = None


def _audio_prop(obj, selector, scope):
    """Read one 32-bit CoreAudio property (object id, four-letter selector, scope). None if unavailable."""
    try:
        ctypes, ca, Addr = _core_audio()
        value, size = ctypes.c_uint32(0), ctypes.c_uint32(4)
        addr = Addr(_fourcc(selector), _fourcc(scope), 0)
        if ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(value)) != 0:
            return None
        return value.value
    except Exception:
        return None


def _audio_list(obj, selector, scope="glob"):
    """Read a CoreAudio property that is a list of object ids. None if unavailable."""
    try:
        ctypes, ca, Addr = _core_audio()
        size = ctypes.c_uint32(0)
        addr = Addr(_fourcc(selector), _fourcc(scope), 0)
        if ca.AudioObjectGetPropertyDataSize(obj, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
            return None
        ids = (ctypes.c_uint32 * (size.value // 4))()
        if ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ids) != 0:
            return None
        return list(ids)
    except Exception:
        return None


def _audio_bundle_id(obj):
    """The bundle id of a CoreAudio process object, or "" (command-line tools and daemons have none)."""
    try:
        ctypes, ca, Addr = _core_audio()
        cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        ref, size = ctypes.c_void_p(), ctypes.c_uint32(ctypes.sizeof(ctypes.c_void_p))
        addr = Addr(_fourcc("pbid"), _fourcc("glob"), 0)
        if ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(ref)) != 0 or not ref.value:
            return ""
        buf = ctypes.create_string_buffer(512)
        ok = cf.CFStringGetCString(ref, buf, 512, 0x08000100)  # UTF-8
        cf.CFRelease(ctypes.c_void_p(ref.value))  # we own it, says the header
        return buf.value.decode(errors="replace") if ok else ""
    except Exception:
        return ""


def _process_name(pid):
    try:
        import ctypes
        buf = ctypes.create_string_buffer(256)
        return buf.value.decode(errors="replace") if ctypes.CDLL(None).proc_name(int(pid), buf, 256) > 0 else ""
    except Exception:
        return ""


def _audio_inputs():
    """Every CoreAudio device that can record: the built-in mic, headsets, AirPods, USB mics. Empty if unavailable."""
    return [dev for dev in _audio_list(1, "dev#") or [] if _audio_list(dev, "stm#", "inpt")]  # has an input stream


def _audio_processes():
    """Every app talking to CoreAudio, and whether it records or plays right now. None where the Mac cannot
    tell us (older than macOS 14.2): the per-app answer is what the orange microphone dot is built on."""
    procs = _audio_list(1, "prs#")
    if procs is None:
        return None
    out = []
    for obj in procs:
        pid = _audio_prop(obj, "ppid", "glob")
        out.append({"pid": pid, "app": _audio_bundle_id(obj) or _process_name(pid) or f"pid {pid}",
                    "input": bool(_audio_prop(obj, "piri", "glob")), "output": bool(_audio_prop(obj, "piro", "glob"))})
    return out


# Always recording, never a person talking: the "Hey Siri" listener and the audio history daemon.
MIC_NEVER_BUSY = ("com.apple.CoreSpeech", "corespeechd", "historicalaudiod")
# Apps you take calls in. Seen recording once, they keep the microphone "busy" while they still play sound,
# because a muted web call lets go of the microphone but you are still listening to people.
CALL_APPS = ("us.zoom.", "com.microsoft.teams", "com.tinyspeck.slackmacgap", "com.hnc.Discord", "com.apple.FaceTime",
             "com.cisco.webex", "com.apple.WebKit.GPU", "com.google.Chrome", "com.brave.Browser",
             "company.thebrowser.Browser", "com.microsoft.edgemac", "org.mozilla.firefox")


def is_call_app(app):
    return any(app.startswith(prefix) for prefix in CALL_APPS)


def remember_call(proc, now):
    atomic_write(CALL_FILE, json.dumps({"app": proc["app"], "pid": proc["pid"], "at": now}))


def last_call():
    try:
        return json.loads(CALL_FILE.read_text())
    except Exception:
        return {}


def mac_mic_user(cfg, now):
    """Who is recording on this Mac, or "". Falls back to the devices where the per-app answer is missing."""
    procs = _audio_processes()
    if procs is None:
        # older macOS: is any real input device running? Virtual and aggregate ones (BlackHole, Loopback)
        # can run all day without a person on the other end, so they do not count
        devices = _audio_inputs() or [_audio_prop(1, "dIn ", "glob")]
        real = [d for d in devices if d and _audio_prop(d, "tran", "glob") not in (_fourcc("virt"), _fourcc("grup"))]
        return "a microphone" if any(_audio_prop(d, "gone", "inpt") for d in real) else ""
    ignore = set(MIC_NEVER_BUSY) | set((cfg or {}).get("mic_ignore_apps") or [])
    recording = [p for p in procs if p["input"] and p["app"] not in ignore and p["pid"] != os.getpid()]
    calls = [p for p in recording if is_call_app(p["app"])]
    if calls:
        remember_call(calls[0], now)
        return calls[0]["app"]
    if recording:
        return recording[0]["app"]
    call = last_call()
    grace = float((cfg or {}).get("call_grace_seconds", DEFAULTS["call_grace_seconds"]))
    if call and now - call.get("at", 0) < grace:
        if any(p["pid"] == call.get("pid") and p["output"] for p in procs):
            return f"{call.get('app')} (call still playing, mic muted)"
    return ""


WINDOWS_MIC = ("$p = 'HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone';"
               "$busy = Get-ChildItem $p -Recurse -ErrorAction SilentlyContinue | "
               "Where-Object { $_.GetValue('LastUsedTimeStop') -eq 0 };"
               "if ($busy) { 'busy' } else { 'free' }")


def mic_in_use(cfg=None):
    """Who is using the microphone right now (an app name), or "" when it is free."""
    if OS == MAC:
        return mac_mic_user(cfg, time.time())
    if OS == WINDOWS:  # Windows records who is using the microphone; an app still using it has no stop time
        try:
            r = subprocess.run(PS + [WINDOWS_MIC], capture_output=True, text=True, timeout=6)
            return "an app" if "busy" in r.stdout else ""
        except Exception:
            return ""
    try:  # Linux: any capture device that ALSA says is running
        for status in Path("/proc/asound").glob("card*/pcm*c/sub*/status"):
            if "state: RUNNING" in status.read_text(errors="replace"):
                return "a capture device"
    except Exception:
        pass
    return ""


def headphones_on():
    """True when sound goes to headphones (Bluetooth like AirPods, or the headphone jack): only you hear it.
    None where this machine cannot tell us."""
    if OS != MAC:
        return None
    dev = _audio_prop(1, "dOut", "glob")  # default output device
    if not dev:
        return False
    transport = _audio_prop(dev, "tran", "glob")
    if transport in (_fourcc("blue"), _fourcc("blea")):
        return True
    return transport == _fourcc("bltn") and _audio_prop(dev, "ssrc", "outp") == _fourcc("hdpn")


def wait_for_mic(cfg):
    """Wait until the microphone is free. Returns True if it is safe to talk."""
    who = cfg.get("wait_for_mic", True) and mic_in_use(cfg)
    if not who:
        return True
    log("mic", "-", f"microphone in use by {who}, holding the voice")
    deadline = time.time() + float(cfg.get("mic_wait_max_seconds", 120))
    while time.time() < deadline:
        time.sleep(1)
        if not mic_in_use(cfg):
            time.sleep(float(cfg.get("mic_settle_seconds", 1.5)))  # let dictation finish its last words
            if not mic_in_use(cfg):
                log("mic", "-", "microphone free, speaking now")
                return True
    log("mic", "-", f"microphone still busy after the wait ({mic_in_use(cfg) or who}), sound only")
    return False


PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
WINDOWS_SPEAK = ("Add-Type -AssemblyName System.Speech;"
                 "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                 "$s.Rate = [int]$env:KOOVI_RATE;"
                 "if ($env:KOOVI_VOICE) { try { $s.SelectVoice($env:KOOVI_VOICE) } catch {} };"
                 "$s.Speak($env:KOOVI_TEXT)")


def voice_installed(name):
    """Is this voice on this Mac? Any language, not only English. True when we cannot tell."""
    if not name:
        return True
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return True  # cannot ask: let `say` decide
    return any(line.startswith(str(name) + " ") for line in out.splitlines())


def speech_command(cfg, text):
    """How to say a line out loud on this machine: (command, extra environment). None if nothing can talk."""
    voice, rate = str(cfg["voice"]), int(cfg["rate"])
    if OS == MAC:
        if voice_installed(voice):
            return ["say", "-v", voice, "-r", str(rate), text], {}
        log("voice", "-", f"voice '{voice}' is not on this Mac, speaking with the system voice instead")
        return ["say", "-r", str(rate), text], {}  # the Mac's own voice, so a wrong name is never silence
    if OS == WINDOWS:
        # Windows counts speed from -10 to 10, where 0 is about 200 words a minute.
        return PS + [WINDOWS_SPEAK], {"KOOVI_TEXT": text, "KOOVI_VOICE": "" if voice.lower() in ("samantha", "koovi") else voice,
                                      "KOOVI_RATE": str(max(-10, min(10, round((rate - 200) / 15))))}
    for program in ("spd-say", "espeak-ng", "espeak", "festival"):
        if shutil.which(program):
            if program == "spd-say":  # speech-dispatcher counts speed from -100 to 100
                return [program, "-w", "-r", str(max(-100, min(100, round((rate - 175) * 100 / 175)))), text], {}
            if program.startswith("espeak"):
                return [program, "-s", str(rate), text], {}
            return ["sh", "-c", 'printf "%s" "$KOOVI_TEXT" | festival --tts'], {"KOOVI_TEXT": text}
    return None, {}


def say_unless_mic(cfg, text):
    """Say the line, watching the microphone the whole time. Stops at once if it opens. True if cut short."""
    watch = cfg.get("wait_for_mic", True)
    if watch and mic_in_use(cfg):  # it may have opened while the music was being turned down
        return True
    command, extra = speech_command(cfg, text)
    if not command:
        log("voice", "-", "ERROR no speech program found. On Linux install one: sudo apt install speech-dispatcher")
        chime(cfg)
        return False
    proc = subprocess.Popen(command, env={**os.environ, **extra})
    deadline = time.time() + 120
    while proc.poll() is None and time.time() < deadline:
        who = watch and mic_in_use(cfg)
        if who:
            proc.terminate()
            log("mic", "-", f"{who} started using the microphone")
            return True
        time.sleep(0.5)  # asking every app about the mic costs coreaudiod some work; twice a second is plenty
    if proc.poll() is None:
        proc.kill()
    return False


@contextlib.contextmanager
def one_at_a_time(path):
    """Hold a lock file so two announcements never talk over each other."""
    STATE_DIR.mkdir(exist_ok=True)
    with open(path, "w") as handle:
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
        elif msvcrt:
            for _ in range(600):  # Windows has no flock: wait for the file to be free
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
        try:
            yield
        finally:
            if msvcrt and not fcntl:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def koovi_is_on():
    """Read straight from the settings file: a switch flipped while a line waits must still count."""
    return load_config().get("enabled", True) is not False


def speak(cfg, text, obey_off=True):
    """Say the line. False when the microphone kept it quiet, so the caller can light the screen instead."""
    with one_at_a_time(SPEECH_LOCK):
        for attempt in (1, 2):  # if the mic opens mid-sentence: stop, wait for it to close, say it once more
            if not wait_for_mic(cfg):
                return False
            if obey_off and not koovi_is_on():
                log("speak", "-", "quiet: Koovi was turned off while the line waited")
                return True  # nothing to make up for with a light: you asked for silence
            saved = duck_music(cfg)
            ducked = duck_browsers(cfg)
            try:
                if saved or ducked:
                    time.sleep(0.3)  # let the music fade before talking
                cut_short = say_unless_mic(cfg, text)
            finally:
                restore_music(saved)
                restore_browsers(cfg, ducked)
            if not cut_short:
                return True
            log("mic", "-", "microphone opened mid-sentence, stopped talking"
                + (", will say it again when the mic closes" if attempt == 1 else ", giving up"))
    return False


LINUX_CHIMES = ("/usr/share/sounds/freedesktop/stereo/complete.oga",
                "/usr/share/sounds/gnome/default/alerts/glass.ogg")


def chime_command(cfg):
    """How to play the short sound on this machine. None if there is nothing to play it with."""
    path = str(cfg.get("chime") or "")
    if OS == MAC:
        return ["afplay", path] if path and Path(path).exists() else None
    if OS == WINDOWS:
        if path.lower().endswith(".wav") and Path(path).exists():
            return PS + [f"(New-Object Media.SoundPlayer '{path}').PlaySync()"]
        return PS + ["[console]::beep(880,180)"]
    sound = path if path and Path(path).exists() else next((s for s in LINUX_CHIMES if Path(s).exists()), "")
    for program in ("paplay", "aplay", "ffplay"):
        if sound and shutil.which(program):
            return [program, sound] if program != "ffplay" else [program, "-nodisp", "-autoexit", "-loglevel", "quiet", sound]
    return ["sh", "-c", "printf '\\a'"]


def chime(cfg):
    command = chime_command(cfg)
    if command:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def pick_line(cfg, kind, project, st, question=""):
    options = cfg["phrases"].get(kind) or DEFAULTS["phrases"][kind]
    options = [o for o in options if isinstance(o, str) and o.strip()]
    if question:  # we know what was asked: prefer the lines that say it
        options = [o for o in options if "{question}" in o] or options
    else:
        options = [o for o in options if "{question}" not in o] or options
    last = st.get("last_line")
    pool = [o for o in options if o != last] or options
    tpl = random.choice(pool)
    st["last_line"] = tpl
    return tpl.format_map(_Safe(assistant=cfg["assistant"], user=cfg["user"], project=project, question=question))


def spawn_detached(*args):
    """Run a Koovi command in the background, so the hook returns to Claude Code at once."""
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *args],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def spawn_worker(job):
    spawn_detached("announce", json.dumps(job))


# ----------------------------------------------------------------------------- screen light

LIGHT_ORDER = {"permission": 0, "asking": 1, "done": 2, "also_done": 2}


def voice_allowed(cfg):
    """May Koovi make a sound right now? Returns (yes/no, why)."""
    mode = str(cfg.get("mode") or "voice").lower()
    if mode == "quiet":
        return False, "quiet mode"
    if mode == "auto":
        wearing = headphones_on()
        if wearing is None:
            return True, "cannot tell if headphones are on, so talking"
        return (True, "headphones on") if wearing else (False, "no headphones")
    return True, "voice mode"


def light_wanted(cfg, voice_ok):
    L = cfg.get("light") or {}
    if not L.get("enabled", True):
        return False
    return str(L.get("when", "instead_of_voice")) == "always" or not voice_ok


def light_render(cfg, st):
    """Write what the screen light shows right now: each flash until its own end time, most urgent first."""
    L = cfg.get("light") or {}
    now = time.time()
    items = []
    for s in st["sessions"].values():
        lt = s.get("light")
        if not lt or s.get("ended") or lt.get("until", 0) <= now:
            continue
        kind = lt.get("kind", "done")
        items.append({"label": lt.get("label", "?"), "kind": kind, "at": lt.get("at", 0), "until": lt.get("until", 0),
                      "text": str(lt.get("detail") or (L.get("labels") or {}).get(kind, kind)),
                      "color": str((L.get("colors") or {}).get(kind, "#ff3b30"))})
    items.sort(key=lambda i: (LIGHT_ORDER.get(i["kind"], 9), i["at"]))
    payload = {"items": items, "pulse": bool(L.get("pulse", True)),
               "corner": str(L.get("corner", "top-right")), "updated": now}
    STATE_DIR.mkdir(exist_ok=True)
    atomic_write(LIGHT_FILE, json.dumps(payload))
    return items


def light_on(cfg, st, s, spoken, kind, now, detail=""):
    """Flash this session on the screen light for a few seconds. Then it is gone, like a spoken line."""
    seconds = float((cfg.get("light") or {}).get("seconds", 5))
    s["light"] = {"label": spoken, "kind": kind, "at": now, "until": now + seconds, "detail": detail}
    light_render(cfg, st)
    spawn_detached("light-start")


def light_clear_all(cfg):
    """Koovi was switched off: nothing stays lit."""
    with locked_state() as st:
        for s in st["sessions"].values():
            s.pop("light", None)
        light_render(cfg, st)


def light_off(cfg, st, s):
    """You replied, or the session closed: end the flash early."""
    if s.pop("light", None) is not None:
        light_render(cfg, st)


def light_commands():
    """Ways to start the screen light on this machine, best first."""
    if OS == WINDOWS:
        if LIGHT_PS1.exists():
            yield ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-WindowStyle", "Hidden", "-File", str(LIGHT_PS1), str(LIGHT_FILE)]
        else:
            log("light", "-", f"ERROR screen light script missing: {LIGHT_PS1}")
        return
    if OS == LINUX:
        log("light", "-", "the screen light needs macOS or Windows; using the voice instead")
        return
    for path in (LIGHT_BUILT, LIGHT_BIN):
        if os.access(path, os.X_OK):
            yield [str(path), str(LIGHT_FILE)]
    if not LIGHT_SRC.exists():
        log("light", "-", f"ERROR helper source missing: {LIGHT_SRC}")
        return
    LIGHT_BUILT.parent.mkdir(parents=True, exist_ok=True)
    build = subprocess.run(["xcrun", "swiftc", "-O", "-o", str(LIGHT_BUILT), str(LIGHT_SRC)],
                           capture_output=True, text=True, timeout=600)
    if build.returncode != 0:
        log("light", "-", f"ERROR could not build the screen light: {build.stderr.strip()[-200:]}")
        return
    log("light", "-", f"built the screen light helper at {LIGHT_BUILT}")
    yield [str(LIGHT_BUILT), str(LIGHT_FILE)]


def flash(cfg, job, kind):
    """Put this job on the screen light."""
    with locked_state() as st:
        s = st["sessions"].setdefault(job["session"], {})
        light_on(cfg, st, s, job["project"], kind, time.time(), detail=job.get("question", ""))


def intimate(cfg, job, line, kind):
    """Get your attention the way the job says: screen light, voice, or both."""
    if not koovi_is_on():
        log("announce", job.get("project", "-"), "quiet: Koovi was turned off before the line was said")
        return
    lit = bool(job.get("light"))
    if lit:
        flash(cfg, job, kind)
    if job.get("voice", True) and not speak(cfg, line) and not lit:
        # the mic stayed busy: you are on a call, so catch your eye instead of making a sound in it
        if (cfg.get("light") or {}).get("enabled", True):
            flash(cfg, job, kind)
            log("mic", "-", "microphone busy, lit the screen instead of speaking")
        else:
            chime(cfg)


def announce_word(job):
    return "SPEAK" if job.get("voice", True) else "LIGHT"


def cmd_light_start():
    """Runs in the background: make sure the screen-light helper is up. A second copy exits by itself."""
    for command in light_commands():
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            return 0  # up and drawing
        if rc == 0:
            return 0  # another helper is already up
        log("light", "-", f"helper {Path(command[-2 if OS == WINDOWS else 0]).name} could not start "
                          f"(code {rc}), trying the next option")
    log("light", "-", "ERROR no working screen light helper")
    return 1


# ----------------------------------------------------------------------------- menu bar icon

def write_shim():
    """~/.koovi/bin/koovi runs the Koovi installed now. Plugin updates move Koovi to a new folder;
    the menu and the login item only ever know this one path."""
    text = ("#!/bin/sh\n# Written by Koovi on every hook. The menu bar icon finds Koovi through this file.\n"
            f'K="{HERE / "koovi.sh"}"\n[ -x "$K" ] && exec "$K" "$@"\nexit 1\n')
    if SHIM.exists() and SHIM.read_text() == text:
        return
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write(SHIM, text)
    SHIM.chmod(0o755)


def menu_owner():
    """(pid, version) of the running menu, or (0, ""). It holds MENU_LOCK while it runs, with both written
    inside; the window list cannot see a menu bar icon on macOS 26."""
    if not fcntl or not MENU_LOCK.exists():
        return 0, ""
    with open(MENU_LOCK, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.seek(0)
            words = handle.read().split()
            pid = int(words[0]) if words and words[0].isdigit() else -1
            return pid, (words[1] if len(words) > 1 else "")
        fcntl.flock(handle, fcntl.LOCK_UN)
        return 0, ""


def menu_running():
    return menu_owner()[0] != 0


def menu_keep_up():
    """Called on every hook: the icon is there, and it is the one for this version of Koovi."""
    write_shim()
    pid, version = menu_owner()
    if pid and version != KOOVI_VERSION:
        menu_stop()  # Koovi was updated; the old menu goes and the new one takes its place
        log("menu", "-", f"replacing the menu bar icon from Koovi {version or 'unknown'}")
        pid = 0
    if not pid:
        spawn_detached("menu-start")


def menu_commands():
    """Ways to start the menu bar icon, best first: the shipped one, else one built here for this version."""
    args = [str(SHIM), KOOVI_VERSION]
    if os.access(MENU_BIN, os.X_OK):
        yield [str(MENU_BIN)] + args
    built = BIN_DIR / f"koovi-menu-{KOOVI_VERSION}"
    if not os.access(built, os.X_OK):
        if not MENU_SRC.exists():
            log("menu", "-", f"ERROR menu source missing: {MENU_SRC}")
            return
        BIN_DIR.mkdir(parents=True, exist_ok=True)
        build = subprocess.run(["xcrun", "swiftc", "-O", "-o", str(built), str(MENU_SRC)],
                               capture_output=True, text=True, timeout=600)
        if build.returncode != 0:
            log("menu", "-", f"ERROR could not build the menu bar icon: {build.stderr.strip()[-200:]}")
            return
        log("menu", "-", f"built the menu bar icon at {built}")
    yield [str(built)] + args


def cmd_menu_start():
    """Runs in the background: put the Koovi icon in the menu bar, unless it is there or you hid it."""
    if OS != MAC or not load_config().get("menu_bar", True):
        return 0
    write_shim()
    for _ in range(10):  # an old copy that was just told to quit lets go of the lock in a moment
        if not menu_running():
            break
        time.sleep(0.2)
    else:
        return 0
    for command in menu_commands():
        errors = STATE_DIR / "menu.err"  # what the menu says when it fails, kept for the diary
        with open(errors, "w") as err:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=err, start_new_session=True)
        try:
            rc = proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            log("menu", "-", "menu bar icon started")
            return 0
        if rc == 0:
            return 0  # another copy is already up
        said = errors.read_text(errors="replace").strip()[-300:]
        if rc in (143, -15) or not load_config().get("menu_bar", True):
            # stopped on purpose (hidden, or replaced) while we watched it start: not a broken icon
            log("menu", "-", "menu bar icon was stopped while starting, so no second try", said=said or None)
            return 0
        sender = re.search(r"SIGTERM from pid (\d+)", said)
        if sender:  # name the process that stopped it, while it may still be there to ask
            name = subprocess.run(["ps", "-p", sender.group(1), "-o", "comm="], capture_output=True, text=True)
            said += f" ({name.stdout.strip() or 'gone already'})"
        log("menu", "-", f"menu bar icon {Path(command[0]).name} could not start (code {rc}), trying the next option",
            said=said or None)
    log("menu", "-", "ERROR no working menu bar icon")
    return 1


def menu_stop():
    pid = menu_owner()[0]
    if pid > 0:
        with contextlib.suppress(OSError):
            os.kill(pid, 15)


def set_login_item(on):
    """Start the menu bar icon when you log in: a LaunchAgent that runs the shim, so updates never break it."""
    if on:
        import plistlib
        write_shim()
        LOGIN_ITEM.parent.mkdir(parents=True, exist_ok=True)
        LOGIN_ITEM.write_bytes(plistlib.dumps({
            "Label": "com.tjmode.koovi.menu", "ProgramArguments": [str(SHIM), "menu-start"],
            "RunAtLoad": True, "AbandonProcessGroup": True}))
    elif LOGIN_ITEM.exists():
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/com.tjmode.koovi.menu"], capture_output=True)
        LOGIN_ITEM.unlink()


def cmd_menu(action="", *args):
    """koovi.sh menu [show|hide|login on|login off]"""
    if OS != MAC:
        print("the menu bar icon is for macOS; use /koovi:settings instead")
        return 1
    if action == "show":
        cmd_set("menu_bar", "true")
        return cmd_menu_start()
    if action == "hide":
        cmd_set("menu_bar", "false")
        menu_stop()
        return 0
    if action == "login" and args and args[0] in ("on", "off"):
        set_login_item(args[0] == "on")
        print(f"start at login: {args[0]}")
        return 0
    if action:
        print("usage: koovi.sh menu [show | hide | login on | login off]")
        return 1
    cfg = load_config()
    print(f"menu bar icon: {'running' if menu_running() else 'not running'}"
          f"{'' if cfg.get('menu_bar', True) else ' (hidden: koovi.sh menu show)'}")
    print(f"start at login: {'on' if LOGIN_ITEM.exists() else 'off'}")
    return 0


# ----------------------------------------------------------------------------- decisions

def announce(cfg, st, s, sid, event, spoken, folder, kind, now, check_focus, question="", **why):
    spoken = spoken_with_session(st, s, sid, folder, spoken, now)
    question = question_snippet(question, max_words=int(cfg.get("question_words") or 8), whole=True)
    voice_ok, sound_note = voice_allowed(cfg)  # sound, or the screen light instead: same ladder either way
    if voice_ok and in_quiet_hours(cfg):
        chime(cfg)
        log(event, spoken, "CHIME quiet hours", kind=kind, **why)
        return
    held = check_focus and cfg.get("focus_check", True) and is_focused(folder)[0]
    reminders = int(cfg["timing"]["reminders"])
    if held:            # you are reading that window already: nothing now, one word later if you never move
        reminders = min(1, reminders)
    elif kind not in (cfg.get("remind_for") or []):
        reminders = 0   # a finished task is said once and never nagged
    if held and not reminders:
        log(event, spoken, "quiet: you are on that window", kind=kind, **why)
        return
    line = pick_line(cfg, kind, spoken, st, question=question)
    s["last_spoken"] = now
    s["last_kind"] = kind
    if kind in ("done", "also_done"):
        st["last_done_spoken_at"] = now
        st["last_done_session"] = sid
    job = {"session": sid, "project": spoken, "folder": folder, "kind": kind, "line": line, "held": held,
           "spoken_at": now, "reminders": reminders,
           "voice": voice_ok, "light": light_wanted(cfg, voice_ok), "question": question}
    spawn_worker(job)
    if held:
        log(event, spoken, f"HOLD {kind}: you are on that window. Only if you do nothing: {line}", **why)
    else:
        log(event, spoken, f"{announce_word(job)} {kind}: {line if voice_ok else sound_note + ', so no sound'}", **why)


# Background task types (Claude Code's labels) that always end and wake the session.
# Shells and monitors can live for hours (dev servers, watchers), so they never hold a "done".
AGENT_TASKS = ("subagent", "workflow")


def task_kinds(running):
    """'shell:27,subagent:2': what was still running, so the diary shows why a "done" was or was not held."""
    counts = {}
    for t in running:
        kind = str(t.get("type") or "?") if isinstance(t, dict) else type(t).__name__
        counts[kind] = counts.get(kind, 0) + 1
    return ",".join(f"{k}:{n}" for k, n in sorted(counts.items())) or None


def capture_background(spoken, running, keep=50):
    """Keep the raw background task list of the last spoken "done"s that had work still running.

    Proof for "it said done while research was still going": the exact types Claude Code sent."""
    try:
        lines = BACKGROUND_FILE.read_text().splitlines()[-(keep - 1):] if BACKGROUND_FILE.exists() else []
        lines.append(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "project": spoken,
                                 "tasks": running}, default=str))
        atomic_write(BACKGROUND_FILE, "\n".join(lines) + "\n")
    except Exception:
        pass


def decide_stop(cfg, st, s, sid, payload, spoken, folder, now):
    if payload.get("stop_hook_active"):
        log("stop", spoken, "quiet: stop_hook_active")
        return
    info = analyze_transcript(payload.get("transcript_path"))
    if payload.get("last_assistant_message"):  # the final text straight from Claude Code; the transcript file may lag
        is_q, q = question_from_text(payload["last_assistant_message"])
        info["is_question"] = is_q or info["ask_tool"]
        if not info["ask_tool"]:
            info["question"] = q
    last_prompt = max(s.get("last_prompt") or 0, s.get("last_wake") or 0) or info["last_user_ts"]
    duration = round(now - last_prompt) if last_prompt else None
    tools = info["tool_uses"]
    running = payload.get("background_tasks") or []  # work still in flight that will wake this session later
    agents = [t for t in running if isinstance(t, dict) and t.get("type") in AGENT_TASKS]
    T = cfg["timing"]
    why = {"took": f"{duration}s" if duration is not None else "unknown", "tools": tools,
           "background": len(running) or None, "agents": len(agents) or None, "kinds": task_kinds(running)}
    asking = info["is_question"] and cfg.get("always_announce_questions", True)
    if not asking:  # a question back to you is always worth a word; other replies must earn it
        if agents and cfg.get("wait_for_agents", True):
            s["awaiting_agents"] = True  # the real finish comes on a later stop, once the agents wake the session
            log("stop", spoken, f"quiet: {len(agents)} agent(s) still working, will report when they finish", **why)
            return
        if running and cfg.get("wait_for_background_tasks", True):
            log("stop", spoken, f"quiet: waiting on {len(running)} background task(s), will report when it wakes", **why)
            return
        if s.pop("awaiting_agents", False):
            # the wrap-up after the agents is often a few seconds long; it is still the end of the whole job
            why["after_agents"] = True
        elif duration is not None and duration < T["min_task_seconds"]:
            log("stop", spoken, "quiet: short turn", **why)
            return
        elif tools == 0 and info["readable"] and (duration is None or duration < T["chat_needs_seconds"]):
            log("stop", spoken, "quiet: chat only, no work done", **why)
            return
    if now - s.get("last_spoken", 0) < T["debounce_seconds"]:
        log("stop", spoken, "quiet: just spoke for this session", **why)
        return
    kind = "asking" if info["is_question"] else "done"
    if (kind == "done" and now - st.get("last_done_spoken_at", 0) < T["also_done_window_seconds"]
            and st.get("last_done_session") != sid):
        kind = "also_done"
    if running and kind != "asking":
        capture_background(spoken, running)
    announce(cfg, st, s, sid, "stop", spoken, folder, kind, now, check_focus=True, question=info["question"], **why)


def decide_permission(cfg, st, s, sid, event, spoken, folder, now, **why):
    """Something is blocked waiting for your yes or no.

    Spoken at once even on that window. You answer these by clicking, and no hook tells us you did,
    so a held permission would speak two minutes after you already said yes."""
    if not cfg.get("permission_always_speak", True):
        chime(cfg)
        log(event, spoken, "CHIME permission", **why)
        return
    if now - s.get("last_spoken", 0) < cfg["timing"]["debounce_seconds"]:
        log(event, spoken, "quiet: just spoke for this session", **why)
        return
    announce(cfg, st, s, sid, event, spoken, folder, "permission", now, check_focus=False, **why)


def decide_notification(cfg, st, s, sid, payload, spoken, folder, now):
    ntype = payload.get("notification_type") or ""
    T = cfg["timing"]
    if ntype == "permission_prompt":
        decide_permission(cfg, st, s, sid, "notification", spoken, folder, now, type=ntype)
    elif ntype == "idle_prompt":
        if s.get("last_spoken", 0) >= s.get("last_prompt", 0) and s.get("last_spoken"):
            log("notification", spoken, "quiet: already announced this turn", type=ntype)
            return
        info = analyze_transcript(payload.get("transcript_path"))
        if not info["is_question"]:
            log("notification", spoken, "quiet: idle, but nothing was asked", type=ntype)
            return
        announce(cfg, st, s, sid, "notification", spoken, folder, "asking", now, check_focus=True,
                 question=info["question"], type=ntype)
    elif ntype in ("agent_completed", "agent_needs_input"):
        if now - s.get("last_spoken", 0) < T["debounce_seconds"]:
            log("notification", spoken, "quiet: just spoke for this session", type=ntype)
            return
        kind = "done" if ntype == "agent_completed" else "asking"
        detail = question_snippet(payload.get("message") or "", whole=True) if kind == "asking" else ""
        announce(cfg, st, s, sid, "notification", f"{spoken} background session", folder, kind, now, check_focus=True,
                 question=detail, type=ntype)
    else:
        log("notification", spoken, "ignored", type=ntype or "?", msg=(payload.get("message") or "")[:80])


# ----------------------------------------------------------------------------- commands

def hook_payload():
    """The JSON the tool sent us, plus the two fields each one names differently."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    roots = payload.get("workspace_roots") or []
    payload["session_id"] = payload.get("session_id") or payload.get("conversation_id") or "unknown"
    payload["cwd"] = payload.get("cwd") or (roots[0] if roots else None) or os.getcwd()
    return payload


def cmd_hook(event):
    payload = hook_payload()
    cfg = load_config()
    sid = payload["session_id"]
    cwd = payload["cwd"]
    now = time.time()
    with locked_state() as st:
        s = st["sessions"].setdefault(sid, {})
        # keep the folder the session started in, even if Claude cd's around later
        folder = s.get("folder") or Path(cwd).name or cwd
        s.update({"folder": folder, "cwd": s.get("cwd") or cwd, "last_seen": now,
                  "first_seen": s.get("first_seen") or now})
        if event in ("stop", "notification", "permission"):
            s["rename"] = session_rename(payload.get("transcript_path")) or s.get("rename", "")
        proj = project_settings(cfg, folder, s.get("rename"))
        spoken = proj["say"]
        if OS == MAC and cfg.get("wait_for_mic", True):
            with contextlib.suppress(Exception):
                mic_in_use(cfg)  # notice a call app on the mic now, so a call muted later is still known as a call
        if OS == MAC and cfg.get("menu_bar", True):
            with contextlib.suppress(Exception):
                menu_keep_up()
        if event == "prompt" and is_system_notice(payload.get("prompt")):
            s["last_wake"] = now  # background work woke the session; you did not type, so nothing is acknowledged
            s["ended"] = False
            log("prompt", spoken, "background work woke the session, not you")
        elif event == "prompt":
            s["last_prompt"] = now
            s["ended"] = False
            s.pop("awaiting_agents", None)  # a new ask from you; any agents still out show up on its stop again
            light_off(cfg, st, s)
            log("prompt", spoken, "noted")
        elif event == "subagent_stop":
            says = " ".join(str(payload.get("last_assistant_message") or "").split()[:8])
            log("subagent", spoken, f"{payload.get('agent_type') or 'subagent'} finished", says=says or None)
        elif event == "session_end":
            s["ended"] = True
            light_off(cfg, st, s)
            log("session_end", spoken, "noted", reason=payload.get("reason"))
        elif not cfg.get("enabled", True):
            log(event, spoken, "quiet: Koovi is off")
        elif proj["mute"]:
            log(event, spoken, "quiet: project is muted")
        elif event == "stop":
            decide_stop(cfg, st, s, sid, payload, spoken, folder, now)
        elif event == "notification":
            decide_notification(cfg, st, s, sid, payload, spoken, folder, now)
        elif event == "permission":
            decide_permission(cfg, st, s, sid, "permission", spoken, folder, now,
                              tool=payload.get("tool_name") or payload.get("command"))
        else:
            log(event, spoken, "unknown event")


def cmd_announce(job_json):
    job = json.loads(job_json)
    cfg = load_config()
    sid, spoken, folder = job["session"], job["project"], job["folder"]
    held = job.get("held")  # you were on that window, so the first word was never said
    if not held:
        intimate(cfg, job, job["line"], job["kind"])
    spoken_at = job["spoken_at"]
    for _ in range(int(job.get("reminders", 0))):
        time.sleep(float(cfg["timing"]["reminder_after_seconds"]))
        cfg = load_config()  # you may have changed something while it waited
        if not cfg.get("enabled", True):
            log("reminder", spoken, "skipped: Koovi is off")
            return
        with locked_state() as st:
            s = st["sessions"].get(sid, {})
            if s.get("last_prompt", 0) > spoken_at:
                log("reminder", spoken, "skipped: you already replied")
                return
            if s.get("ended"):
                log("reminder", spoken, "skipped: session closed")
                return
            if s.get("last_spoken", 0) > spoken_at:
                log("reminder", spoken, "skipped: something newer was announced")
                return
            if in_quiet_hours(cfg):
                log("reminder", spoken, "skipped: quiet hours")
                return
            if not held and cfg.get("focus_check", True) and is_focused(folder)[0]:
                log("reminder", spoken, "skipped: you are on that window")
                return
            kind = job["kind"] if held else "reminder"  # a held job finally says the line it was holding
            line = job["line"] if held else pick_line(cfg, "reminder", spoken, st, question=job.get("question", ""))
            now = time.time()
            s["last_spoken"] = now
            spoken_at = now
            log("reminder", spoken, f"{announce_word(job)} {kind}: {line}")
        intimate(cfg, job, line, kind)


def cmd_test(kind="done", project="Payments", *question):
    cfg = load_config()
    if kind not in DEFAULTS["phrases"]:
        print(f"unknown kind '{kind}'. choose one of: {', '.join(DEFAULTS['phrases'])}")
        return 1
    with locked_state() as st:
        line = pick_line(cfg, kind, project, st, question=" ".join(question))
    heard = cfg["voice"] if (OS != MAC or voice_installed(cfg["voice"])) else "the Mac's own voice"
    print(off_notice(cfg) + f"[{heard}] {line}")
    speak(cfg, line, obey_off=False)
    log("test", project, f"SPEAK {kind}: {line}")
    return 0


def cmd_light(*args):
    cfg = load_config()
    what = (args[0] if args else "status").lower()
    if what == "off":
        with locked_state() as st:
            cleared = sum(1 for s in st["sessions"].values() if s.pop("light", None) is not None)
            light_render(cfg, st)
        print(f"screen light cleared ({cleared} item(s))")
        return 0
    if what == "test":
        demo = (("light-demo-1", "Checkout", "done"), ("light-demo-2", "Payments", "asking"))
        now = time.time()
        seconds = float((cfg.get("light") or {}).get("seconds", 5))
        with locked_state() as st:
            for sid, label, kind in demo:
                st["sessions"][sid] = {"folder": label, "first_seen": now, "last_seen": now}
                light_on(cfg, st, st["sessions"][sid], label, kind, now)
        print(f"demo light on for {seconds:g} seconds: look at the edges of your screens")
        time.sleep(seconds + 1)
        with locked_state() as st:
            for sid, _, _ in demo:
                st["sessions"].pop(sid, None)
            light_render(cfg, st)
        print("demo light off")
        return 0
    voice_ok, note = voice_allowed(cfg)
    L = cfg.get("light") or {}
    shown = "off" if not L.get("enabled", True) else f"on, shown {str(L.get('when', 'instead_of_voice')).replace('_', ' ')}"
    print(f"mode: {cfg.get('mode', 'voice')} ({note});  screen light: {shown}")
    with locked_state() as st:
        items = light_render(cfg, st)
    for it in items:
        print(f"  {it['label']}  {it['text']}")
    if not items:
        print("  nothing on the screen light right now")
    return 0


def cmd_log(n="30"):
    try:
        lines = LOG_FILE.read_text().splitlines()
    except OSError:
        print("no log yet")
        return 0
    print("\n".join(lines[-int(n):]))
    return 0


def cmd_mic():
    """Everything Koovi sees about the microphone, to paste when it talked into a call."""
    cfg = load_config()
    who = mic_in_use(cfg)
    print(f"microphone in use by {who}" if who else "microphone free")
    if OS != MAC:
        return 0
    procs = _audio_processes()
    if procs is None:
        print("per-app check: not available on this Mac (needs macOS 14.2 or newer), checking devices instead")
    else:
        ignore = set(MIC_NEVER_BUSY) | set(cfg.get("mic_ignore_apps") or [])
        for p in procs:
            if p["input"] or p["output"]:
                what = "+".join(k for k in ("input", "output") if p[k])
                note = " (ignored)" if p["app"] in ignore else (" (call app)" if is_call_app(p["app"]) else "")
                print(f"  {p['app']:<45} pid {p['pid']:<7} {what}{note}")
    call = last_call()
    if call:
        print(f"last call app on the mic: {call.get('app')}, {round(time.time() - call.get('at', 0))}s ago"
              f" (counts for {cfg.get('call_grace_seconds')}s while it plays sound)")
    for dev in _audio_inputs():
        tran = (_audio_prop(dev, "tran", "glob") or 0).to_bytes(4, "big").decode(errors="replace")
        default = " default" if dev == _audio_prop(1, "dIn ", "glob") else ""
        print(f"  input device {dev}: {tran}{default}, running={_audio_prop(dev, 'gone', 'inpt')}")
    return 0


def claude_plugin_enabled():
    """True when Koovi is installed as a Claude Code plugin, which carries its own hooks."""
    try:
        enabled = json.loads((Path.home() / ".claude" / "settings.json").read_text()).get("enabledPlugins") or {}
    except Exception:
        return False
    return any(name.split("@")[0] == "koovi" and on for name, on in enabled.items())


def cmd_doctor():
    ok = True

    def check(label, good, hint=""):
        nonlocal ok
        ok = ok and bool(good)
        print(f"  [{'ok' if good else 'XX'}] {label}" + (f"  ->  {hint}" if (hint and not good) else ""))

    print(f"Koovi {KOOVI_VERSION} doctor  ({OS}, python {sys.version.split()[0]} at {sys.executable})")
    try:
        parse_yaml(ensure_config().read_text())
        readable, problem = True, ""
    except Exception as exc:
        readable, problem = False, str(exc)
    check(f"settings file reads ({CONFIG_PATH})", readable, f"fix this line: {problem}")
    cfg = load_config()
    print("  " + off_notice(cfg) if off_notice(cfg) else "", end="")
    if OS == MAC and cfg.get("menu_bar", True):
        check("menu bar icon running", menu_running(),
              "it starts with your next Claude Code message, or now with: koovi.sh menu show. "
              "Running but not visible? System Settings > Menu Bar > Allow in the Menu Bar, or the notch is hiding it")
    command, _ = speech_command(cfg, "test")
    check("something on this machine can talk", bool(command),
          "install a speech program: sudo apt install speech-dispatcher")
    if OS == MAC:
        here = voice_installed(cfg["voice"])
        check(f"voice '{cfg['voice']}'" + ("" if here else " is not on this Mac, so the system voice is used"
                                                          " (see: koovi voices)"), True)
    else:
        names = installed_voices()
        if names:
            check(f"voice '{cfg['voice']}' installed", str(cfg["voice"]) in names,
                  f"pick one of: {', '.join(names[:8])}{' ...' if len(names) > 8 else ''}  (koovi voices)")
    app, title = front_window()
    check("focus check works" + ("" if app else f" (not available on {OS})"), bool(app) or not front_window_command(),
          "the focus check will be skipped; Koovi speaks anyway")
    if claude_plugin_enabled():
        check("Claude Code: installed as a plugin (it brings its own hooks)", True)
    for tool, required, path, events in (
            ("Claude Code", not claude_plugin_enabled(), Path.home() / ".claude" / "settings.json",
             ("UserPromptSubmit", "Stop", "Notification", "SessionEnd", "SubagentStop")),
            ("Codex", False, Path.home() / ".codex" / "hooks.json",
             ("UserPromptSubmit", "Stop", "PermissionRequest", "SessionEnd", "SubagentStop")),
            ("Cursor", False, Path.home() / ".cursor" / "hooks.json",
             ("beforeSubmitPrompt", "stop", "sessionEnd"))):
        if not path.parent.exists() or (tool == "Claude Code" and not required):
            continue  # the plugin line above already covered Claude Code
        try:
            hooks = (json.loads(path.read_text()) if path.exists() else {}).get("hooks", {})
            found = [ev for ev in events if any("koovi" in json.dumps(entry) for entry in hooks.get(ev, []))]
        except Exception as exc:
            check(f"{tool} hooks ({path})", not required, str(exc))
            continue
        if len(found) == len(events):
            check(f"{tool}: set up", True)
        elif required:
            check(f"{tool} hooks ({path})", False, f"set up for {found or 'nothing'}; run: python3 install.py")
        else:
            check(f"{tool}: not set up. Only needed if you use it: python3 install.py --{tool.split()[0].lower()}", True)
    sites = [str(x) for x in (cfg.get("browser_music_sites") or [])]
    for app, flavor in _running_browsers():
        status, info = _run_browser_js(app, flavor, "1", sites)
        if status == "ok":
            check(f"{app}: can pause music tabs" + ("" if info else " (no music tab open right now)"), True)
        elif status == "off":  # a switch you turn on once, and only if you play music in a browser
            check(f"{app}: music tabs keep playing unless you switch on: {info}", True)
        elif "timed out" in info.lower() or "TimeoutExpired" in info:
            check(f"{app}: did not answer in time; music tabs may stay loud", True)
        else:
            check(f"{app}: cannot turn down music tabs ({info[:60]})", True)
    audio_ok = _audio_prop(1, "dIn ", "glob") is not None if OS == MAC else True
    who = mic_in_use(cfg) if audio_ok else ""
    check("microphone check works" + ((f" (in use by {who} right now)" if who else " (mic is free right now)") if audio_ok else ""),
          audio_ok, "the sound system did not answer; Koovi will talk without waiting for the mic")
    STATE_DIR.mkdir(exist_ok=True)
    voice_ok, note = voice_allowed(cfg)
    check(f"mode '{cfg.get('mode', 'voice')}': {note}" + ("" if voice_ok else ", screen light instead of sound"), True)
    if OS == LINUX:
        check("screen light (not available on Linux; the voice is used instead)", True)
    elif OS == WINDOWS:
        check(f"screen light script ({LIGHT_PS1})", LIGHT_PS1.exists(), "the file is missing from this copy of Koovi")
    else:
        helper = next((path for path in (LIGHT_BUILT, LIGHT_BIN) if os.access(path, os.X_OK)), None)
        can_build = subprocess.run(["xcrun", "-f", "swiftc"], capture_output=True).returncode == 0
        check("screen light helper" + (f" ({helper})" if helper else " (will be built on first use)"),
              bool(helper) or can_build, "no helper and no Swift compiler; run: xcode-select --install")
    check(f"state folder writable ({STATE_DIR})", os.access(STATE_DIR, os.W_OK))
    print("all good" if ok else "something needs attention (see XX lines)")
    return 0 if ok else 1


def installed_voices():
    """The names this machine can speak with. Empty when we cannot ask it."""
    try:
        if OS == MAC:
            out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
            return sorted({m.group(1).strip() for m in (re.match(r"^(.*?)\s+en_[A-Z]{2}\b", ln) for ln in out.splitlines()) if m})
        if OS == WINDOWS:
            out = subprocess.run(PS + ["Add-Type -AssemblyName System.Speech;"
                                       "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices()"
                                       " | ForEach-Object { $_.VoiceInfo.Name }"],
                                 capture_output=True, text=True, timeout=20).stdout
            return sorted({ln.strip() for ln in out.splitlines() if ln.strip()})
    except Exception:
        pass
    return []


def cmd_voices():
    names = installed_voices()
    if names:
        print("\n".join(names))
    elif OS == LINUX:
        program = next((x for x in ("spd-say", "espeak-ng", "espeak", "festival") if shutil.which(x)), None)
        print(f"speaking with {program}; it chooses the voice" if program
              else "no speech program found. Install one: sudo apt install speech-dispatcher")
    else:
        print("could not ask this machine for its voices")
    return 0


def _yaml_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return text if re.fullmatch(r"[A-Za-z0-9 ._/-]+", text) else json.dumps(text)


def set_config_value(path, value):
    """Change one setting in your config file, keeping comments and order. Use a dot for a nested key: light.enabled"""
    with one_at_a_time(CONFIG_LOCK):
        lines = readable_config_lines()
        _set_line(lines, path, value)
        atomic_write(CONFIG_PATH, "\n".join(lines) + "\n")


class SettingsUnreadable(Exception):
    """The settings file has a line Koovi cannot read, so writing it now could throw your other settings away."""


def readable_config_lines():
    ensure_config()
    text = CONFIG_PATH.read_text()
    try:
        parse_yaml(text)
    except ValueError as exc:
        raise SettingsUnreadable(str(exc)) from None
    return text.splitlines()


def _set_line(lines, path, value):
    keys = path.split(".")
    parent_indent, start, end = -1, 0, len(lines)
    for depth, key in enumerate(keys):
        hit = None
        for i in range(start, end):
            m = re.match(r"^(\s*)([^#:]+?):(.*)$", lines[i])
            if m and len(m.group(1)) > parent_indent and m.group(2).strip().strip("\"'") == key:
                if depth == len(keys) - 1 or m.group(3).strip() == "":
                    hit = (i, len(m.group(1)))
                    break
        if hit is None:
            entry = " " * (parent_indent + 2 if parent_indent >= 0 else 0) + f"{key}:"
            if depth == len(keys) - 1:
                lines.insert(end, f"{entry} {_yaml_value(value)}")
                break
            lines.insert(end, entry)
            hit = (end, parent_indent + 2 if parent_indent >= 0 else 0)
        i, indent = hit
        if depth == len(keys) - 1:
            m = re.match(r"^(\s*[^#:]+?:\s*)([^#]*?)(\s*#.*)?$", lines[i])
            lines[i] = m.group(1) + _yaml_value(value) + (("  " + m.group(3).strip()) if m.group(3) else "")
            break
        parent_indent, start = indent, i + 1
        end = next((j for j in range(start, len(lines)) if lines[j].strip() and not lines[j].startswith(" " * (indent + 1))), len(lines))


def set_project_mute(folder, mute):
    """Mute or unmute one project folder in your config file."""
    with one_at_a_time(CONFIG_LOCK):
        lines = readable_config_lines()
        _mute_line(lines, folder, mute)
        atomic_write(CONFIG_PATH, "\n".join(lines) + "\n")


def _mute_line(lines, folder, mute):
    head = next((i for i, ln in enumerate(lines) if re.match(r"^projects:\s*(#.*)?$", ln)), None)
    if head is None:
        lines += ["projects:"]
        head = len(lines) - 1
    end = next((j for j in range(head + 1, len(lines)) if lines[j].strip() and not lines[j].startswith(" ")), len(lines))
    entry = {"mute": mute}
    for i in range(head + 1, end):
        key, rest = _split_key(_strip_comment(lines[i]).strip())
        if key == folder:
            current = _scalar(rest)
            if isinstance(current, str):
                entry["say"] = current
            elif isinstance(current, dict) and current.get("say"):
                entry["say"] = current["say"]
            del lines[i]
            end -= 1
            break
    parts = ([f'say: {_yaml_value(entry["say"])}'] if entry.get("say") else []) + [f"mute: {_yaml_value(mute)}"]
    lines.insert(end, f"  {_yaml_value(folder)}: {{ {', '.join(parts)} }}")


MODES = {"voice": "speaks out loud", "quiet": "screen light only, no sound",
         "auto": "speaks on headphones, screen light on speakers"}


def setting_problem(key, value):
    """What is wrong with writing VALUE to KEY, or "" when it is fine."""
    node = DEFAULTS
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return f"there is no setting called '{key}'. The names are in {CONFIG_PATH}"
        node = node[part]
    if isinstance(node, (dict, list)):
        return f"'{key}' holds several values. Change it in {CONFIG_PATH}"
    if key == "mode" and value not in MODES:
        return "mode is voice, quiet or auto"
    if key.startswith("quiet_hours."):
        if value in (None, False) or re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(value)):
            return ""
        return f"{key} is a time like 23:00, or off"
    if isinstance(node, bool) and not isinstance(value, bool):
        return f"{key} is true or false"
    if isinstance(node, (int, float)) and not isinstance(node, bool) and (
            isinstance(value, bool) or not isinstance(value, (int, float))):
        return f"{key} is a number"
    return ""


def cmd_set(key="", *value):
    if not key or not value:
        print("usage: koovi.sh set KEY VALUE     (KEY like mode, voice, rate, user, light.enabled)")
        return 1
    new = _scalar(" ".join(value))
    problem = setting_problem(key, new)
    if problem:
        print(f"not changed: {problem}")
        return 1
    if key.startswith("quiet_hours.") and new is False:
        new = None  # "off" leaves the time empty
    try:
        set_config_value(key, new)
    except SettingsUnreadable as exc:
        print(f"not changed: your settings file has a line Koovi cannot read ({exc}). Fix it in {CONFIG_PATH}")
        return 1
    print(f"{key} set to {_yaml_value(new) or 'off'}")
    if key == "menu_bar" and new is True and OS == MAC:
        spawn_detached("menu-start")
    if key == "enabled" and new is False:
        light_clear_all(load_config())
        print("Koovi is off. It keeps track of your sessions but will not speak or flash until you turn it on.")
    return 0


def cmd_mute(mute, *folder):
    name = " ".join(folder).strip() or Path.cwd().name
    try:
        set_project_mute(name, mute)
    except SettingsUnreadable as exc:
        print(f"not changed: your settings file has a line Koovi cannot read ({exc}). Fix it in {CONFIG_PATH}")
        return 1
    print(f"{name}: {'muted' if mute else 'unmuted'}")
    return 0


def off_notice(cfg):
    if cfg.get("enabled", True) is False:
        return "Koovi is OFF: it will not speak or flash. Turn it on with /koovi:settings or: koovi.sh set enabled true\n"
    return ""


def settings_snapshot():
    """The main switches as they are right now, for /koovi:settings and the menu bar."""
    cfg = load_config()
    try:
        parse_yaml(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else None
        error = ""
    except Exception as exc:
        error = str(exc)
    try:
        st = json.loads(STATE_FILE.read_text())
    except Exception:
        st = {}
    sessions = sorted((st.get("sessions") or {}).values(), key=lambda s: -float(s.get("last_seen") or 0))
    recent = list(dict.fromkeys(str(s["folder"]) for s in sessions if s.get("folder")))
    mic = None
    if cfg.get("wait_for_mic", True):
        with contextlib.suppress(Exception):
            mic = mic_in_use(cfg) or ""
    q = cfg.get("quiet_hours") or {}
    return {
        "version": KOOVI_VERSION,
        "config_path": str(CONFIG_PATH),
        "error": error,
        "enabled": cfg.get("enabled", True) is not False,
        "mode": str(cfg.get("mode") or "voice").lower(),
        "wait_for_mic": bool(cfg.get("wait_for_mic", True)),
        "mic": mic,
        "wait_for_agents": bool(cfg.get("wait_for_agents", True)),
        "quiet_hours": {"start": q.get("start"), "end": q.get("end")},
        "muted": [k for k, v in (cfg.get("projects") or {}).items() if isinstance(v, dict) and v.get("mute")],
        "recent_projects": recent,
        "mic_name": app_name(mic) if mic else mic,
        "last_said": last_said(),
        "menu_bar": cfg.get("menu_bar", True) is not False,
        "login": LOGIN_ITEM.exists(),
    }


APP_NAMES = (("us.zoom.", "Zoom"), ("com.microsoft.teams", "Teams"), ("com.tinyspeck.slackmacgap", "Slack"),
             ("com.hnc.Discord", "Discord"), ("com.apple.FaceTime", "FaceTime"), ("com.cisco.webex", "Webex"),
             ("com.apple.WebKit", "Safari"), ("com.google.Chrome", "Chrome"), ("com.brave.Browser", "Brave"),
             ("company.thebrowser.", "Arc"), ("com.microsoft.edgemac", "Edge"), ("org.mozilla.firefox", "Firefox"))


def app_name(who):
    """us.zoom.xos -> Zoom. Anything else stays as macOS named it."""
    return next((name for prefix, name in APP_NAMES if str(who).startswith(prefix)), str(who))


def last_said():
    """The last line Koovi spoke or flashed, from the diary: {"line", "at"} or None."""
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - 20000))
            lines = f.read().decode(errors="replace").splitlines()
    except OSError:
        return None
    for ln in reversed(lines):
        parts = ln.split(" | ", 3)
        m = len(parts) == 4 and re.match(r"(?:SPEAK|LIGHT) \w+: (.*?)(?: \w+=\S+)*$", parts[3])
        if m:
            return {"line": m.group(1), "at": parts[0]}
    return None


def cmd_settings(*args):
    snap = settings_snapshot()
    if "--json" in args:
        print(json.dumps(snap))
        return 1 if snap["error"] else 0
    if snap["error"]:
        print(f"ERROR your settings file has a line Koovi cannot read: {snap['error']}")
        print(f"Nothing can be changed until it is fixed in {snap['config_path']}  (/koovi:doctor shows more)")
        return 1
    on = lambda yes: "on" if yes else "off"
    mode = snap["mode"]
    print(f"Koovi is {'ON' if snap['enabled'] else 'OFF'}" + (f" · {MODES.get(mode, mode)} (mode: {mode})" if snap["enabled"] else ""))
    now = ""
    if snap["wait_for_mic"]:
        now = " · right now: " + (snap["mic_name"] or "nothing") if snap["mic"] is not None else " · right now: cannot tell"
    print(f"Stay quiet during calls (wait_for_mic): {on(snap['wait_for_mic'])}{now}")
    print(f"Wait for research to finish (wait_for_agents): {on(snap['wait_for_agents'])}")
    q = snap["quiet_hours"]
    print("Quiet hours: " + (f"{q['start']} to {q['end']}" if q["start"] and q["end"] else "off"))
    print("Muted projects: " + (", ".join(snap["muted"]) or "none"))
    print(f"Settings file: {snap['config_path']}")
    return 0


def cmd_status():
    cfg = load_config()
    print(off_notice(cfg) + f"Koovi {KOOVI_VERSION}  settings: {CONFIG_PATH if CONFIG_PATH.exists() else 'built-in defaults (no settings file yet)'}")
    cmd_light()
    muted = [k for k, v in (cfg.get("projects") or {}).items() if isinstance(v, dict) and v.get("mute")]
    print("muted projects: " + (", ".join(muted) if muted else "none"))
    print("last decisions:")
    cmd_log("3")
    return 0


def cmd_voice(*name):
    name = " ".join(name).strip()
    if not name:
        print("usage: koovi.sh voice NAME   (see: koovi.sh voices)")
        return 1
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    if not any(ln.startswith(name + " ") for ln in out.splitlines()):
        print(f"'{name}' is not installed. Run: koovi.sh voices")
        return 1
    try:
        set_config_value("voice", name)
    except SettingsUnreadable as exc:
        print(f"not changed: your settings file has a line Koovi cannot read ({exc}). Fix it in {CONFIG_PATH}")
        return 1
    print(f"voice set to '{name}' in {CONFIG_PATH}")
    return cmd_test("done", "Payments")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, args = argv[1], argv[2:]
    if cmd in ("prompt", "stop", "notification", "session_end", "subagent_stop", "permission"):
        try:
            cmd_hook(cmd)
        except Exception as exc:  # never break Claude Code because of us
            log(cmd, "-", f"ERROR {type(exc).__name__}: {exc}")
        return 0
    if cmd == "announce":
        try:
            cmd_announce(args[0])
        except Exception as exc:
            log("announce", "-", f"ERROR {type(exc).__name__}: {exc}")
        return 0
    if cmd == "test":
        return cmd_test(*args)
    if cmd == "log":
        return cmd_log(*args)
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "mic":
        return cmd_mic()
    if cmd == "light":
        return cmd_light(*args)
    if cmd == "light-start":
        return cmd_light_start()
    if cmd == "menu-start":
        return cmd_menu_start()
    if cmd == "menu":
        return cmd_menu(*args)
    if cmd == "voices":
        return cmd_voices()
    if cmd == "voice":
        return cmd_voice(*args) if args else cmd_set("mode", "voice")
    if cmd in ("quiet", "auto"):
        return cmd_set("mode", cmd)
    if cmd == "set":
        return cmd_set(*args) if args else cmd_set("")
    if cmd == "mute":
        return cmd_mute(True, *args)
    if cmd == "unmute":
        return cmd_mute(False, *args)
    if cmd == "status":
        return cmd_status()
    if cmd == "settings":
        return cmd_settings(*args)
    if cmd == "version":
        print(KOOVI_VERSION)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
