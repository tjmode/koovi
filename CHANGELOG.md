# Changelog

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
