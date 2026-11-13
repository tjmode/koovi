# Changelog

## 1.0.0

- Koovi 1.0: voice or screen light, quiet during calls, waits for research, an off switch,
  `/koovi:settings` and the menu bar icon.
- Chats in Claude Desktop that have no project are called by their name. Their folder is called
  something like `scratch-2026-11-11-47c6d0`, and Koovi read that out loud: "scratch 2026 11 11
  47c6d0 is done". Now it says "Gold coin portfolio valuation is done", or "scratch chat" when the
  chat has no name yet. A name you set under `projects:` still wins.
- Videos and music in browser tabs are paused while Koovi talks, and play on from the same spot
  after, so you miss nothing. `browser_pause: false` turns them down as before. A tab paused more
  than ten minutes ago is never started again. Brave and Chrome still need View > Developer >
  Allow JavaScript from Apple Events.
- The diary now names the kinds of background work still running when a turn ends, like
  `kinds=shell:27,subagent:2`. When Koovi says "done" while work still runs, the exact list from
  Claude Code is kept in `~/.koovi/background.jsonl`, to find out why it spoke during research.

## 0.12.0

- A Koovi icon in the Mac menu bar. One click shows whether Koovi is on, how it reaches you,
  whether it stays quiet during calls (with the app holding the microphone right now, like
  "Zoom is using the mic"), whether it waits for research, quiet hours, muted projects, a test
  line and the last thing it said. The icon gets a slash while Koovi is off.
- It appears with the first message in any session, and is replaced by itself when Koovi updates.
  "Start at login" keeps it after a restart; "Hide from menu bar" removes it until
  `/koovi:koovi menu show`.
- It is only a face: every change goes through `koovi.sh set` into the same settings file, and it
  wakes only when that file changes or you open it.
- `/koovi:doctor` says whether the icon is running, and where to look when macOS hides it.

## 0.11.0

- `/koovi:settings`: the main switches in one place, changed by clicking. On or off, voice or
  screen light, quiet during calls, wait for research. Each one shows how it is set now, and
  only what you change is written.
- An off switch, `enabled`. Off means no voice, no screen light and no chime, while Koovi still
  keeps track of your sessions, so turning it back on picks up cleanly. A light that is showing
  goes out, and `/koovi:status`, `/koovi:test` and `/koovi:doctor` say "Koovi is OFF" first.
- A change now reaches lines already waiting. A reminder, or a line held while your microphone was
  busy, reads the settings again before it speaks, so off really means off and a new mode counts.
- `koovi.sh settings` prints the main switches, `--json` for scripts and the coming menu bar icon.
- `/koovi:set` checks what it writes: a setting that does not exist, or a value of the wrong kind,
  is refused with a reason instead of saved silently. Quiet hours take a time like 23:00, or off.
- Settings are never written over a file Koovi cannot read, and two changes at the same moment
  both land.

## 0.10.2

- Never speaks into a call on a headset. Koovi only looked at the Mac's default microphone, so a
  meeting on AirPods or a headset, where the call app records from the headset mic, looked like a
  free microphone. It now asks macOS which app is recording, on any microphone, and the diary names
  it: "microphone in use by us.zoom.xos". Playing sound no longer counts as recording, so music
  through a headset, or Koovi's own voice, no longer looks like a call. "Hey Siri" is ignored.
- A muted call still counts. Google Meet and other web calls let go of the microphone when you
  mute, so a call app seen on the microphone keeps Koovi quiet for `call_grace_seconds` (10
  minutes) while it is still playing sound.
- `mic_ignore_apps` for tools that hold the microphone all day, like noise filters.
- `koovi mic` shows every app using sound right now, the last call seen, and each microphone, to
  paste when Koovi talked when it should not have.
- On a Mac older than 14.2, which cannot say which app records, Koovi checks every real
  microphone and skips virtual ones like BlackHole.
- When the microphone stays busy for the whole wait, the screen lights instead of a chime.
- Research agents no longer get you a false "done". Claude ends its turn while subagents and
  workflows work in the background; Koovi now waits for them and speaks when the job is really
  finished. Shells and watchers still never hold it back. `wait_for_agents` turns this off.

## 0.10.1

- Stopped reading your own words back at you. When two live sessions share a folder, Koovi told
  them apart with the first few words of your last message, so it announced "Koovi project, the
  Base directory for this skill Run session has finished" out loud and printed the same on the
  screen light. Only a name you gave a session with /rename is spoken now, cut to three words;
  otherwise they are simply session 1 and session 2.
- One less transcript read on every hook, since nothing needs your last request any more.

## 0.10.0

- Shorter lines. It says what happened and stops: "Payments asks: Postgres or SQLite?" The question
  is cut to the first eight words, set by `question_words`, and the sentences around it lost their
  flourishes. A line should be over in about three seconds.
- A window you are already reading hears nothing. Koovi holds the line instead of speaking over
  what you are looking at, and says it once only if you still have not typed anything by
  `reminder_after_seconds`. Held or not, you hear a session at most twice, and this way at most
  once. `focus_check` is on by default now; set it to false to go back to speaking every time.
- Permission requests are the exception and still speak at once. You answer those by clicking, and
  no hook tells Koovi that you did, so a held one would fire long after you said yes.

## 0.9.9

- The nine new commands from 0.9.8 never appeared. Their descriptions read "Koovi: ..." and that
  second colon makes the file's header invalid, so Claude Code skipped every one of them. Only
  the old catch-all survived, which is why the picker still showed a single command.

## 0.9.8

- One command per job: `/koovi:status`, `/koovi:doctor`, `/koovi:log`, `/koovi:quiet`,
  `/koovi:voice`, `/koovi:mute`, `/koovi:unmute`, `/koovi:test`, `/koovi:set`. Type `/koovi:`
  and they all appear, instead of remembering words to pass to one command.

## 0.9.7

- The command is `/koovi:koovi`, not `/koovi`. Claude Code puts every plugin command behind the
  plugin's name, and the README said otherwise. Type `/koo` and it appears.

## 0.9.6

- Fixed the bug that made a brand new install say nothing at all. The settings file ships with
  `projects:` and only comments under it, which reads as empty rather than as a list, and every
  announcement then failed with `AttributeError: 'NoneType' object has no attribute 'get'`.
  A heading with nothing under it now means "leave this alone".
- The doctor no longer reports Codex and Cursor as faults when you only use Claude Code, and a
  slow or switched-off browser check is a note rather than a failure.

## 0.9.5

- A voice name that is not on this Mac no longer risks silence. Koovi checks first, speaks with
  the Mac's own voice instead, and says so in the log. Not every macOS version falls back on its
  own, and the shipped default, Samantha, is not on every Mac.
- The doctor's voice check covers voices in any language, not only English ones.

## 0.9.4

- Dropped `displayName` from the marketplace entry. Older Claude Code versions reject unknown
  keys there, so `plugin marketplace add tjmode/koovi` failed with "Invalid schema". The name
  still comes from plugin.json, which every version reads.

## 0.9.3

- A spoken line that does not use your name: "Koovi reporting. Checkout is done."
  Both names, what it calls itself and what it calls you, were always yours to change;
  now the README says so.

## 0.9.2

- Rewritten README: full reference tables for the commands, the rules and every setting.
- The built-in default for `timing.min_task_seconds` was 30 while the shipped settings said 5.
  Both are 5 now, and a test keeps them in step.

## 0.9.1

- The doctor no longer reports a problem when Koovi is installed as a Claude Code plugin.
  Plugins carry their own hooks, so there is nothing in settings.json to find.

## 0.9.0

First public release, macOS only.

- Speaks which session finished or needs you, by project name.
- Says what the question is when it can read one: "Checkout is asking: which database should we use?"
- Quiet rules: short turns, chat-only replies and muted projects stay silent.
- One announcement, one reminder for questions and permission requests, then nothing more.
- Your next message in that window counts as the answer and cancels the reminder.
- Screen light for offices: a five-second frame on every monitor instead of the voice.
- Modes: voice, quiet, and auto, which talks only when headphones are the output.
- Waits while your microphone is in use, and stops mid-sentence if it opens.
- Turns Apple Music, Spotify and browser music tabs down while it talks.
- Knows about background tasks: a turn with work still running is not announced as done.
- A diary of every decision, in plain words: `/koovi log`.
- No Python packages to install. The settings file is read by Koovi itself.
- Works with Codex and Cursor as well as Claude Code, from one install.
- Reads Codex transcripts as well as Claude Code ones.
- Announces Codex permission requests.
- Windows and Linux support: voice, sound, focus check, microphone check, file locking,
  and a screen light for Windows. Written but not yet tried on a real machine.
