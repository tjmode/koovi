# Koovi

[![tests](https://github.com/tjmode/koovi/actions/workflows/ci.yml/badge.svg)](https://github.com/tjmode/koovi/actions/workflows/ci.yml)
[![version](https://img.shields.io/badge/version-0.9.4-2ea44f)](CHANGELOG.md)
[![licence](https://img.shields.io/badge/licence-MIT-blue)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-ready-black?logo=apple&logoColor=white)](#platforms)
[![Claude Code · Codex · Cursor](https://img.shields.io/badge/Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Cursor-supported-6b46c1)](#install)

**Koovi tells you which of your coding sessions just finished or needs an answer.** Work in one
window while three others run.

```
"Koovi reporting. Checkout is done."
"Payments is asking: should we use Postgres or SQLite?"
```

One line, one reminder if you do not reply, then silence. Your next message in that window is the
answer.

> [!TIP]
> Nothing about the voice is fixed. `koovi set assistant Jarvis` changes what it calls itself,
> `koovi set user bro` changes what it calls you, and `koovi voice Daniel` changes the voice
> itself. The sentences are a plain list in your settings file, so you can rewrite them or add
> your own.

## Install

**Claude Code** (one line at a time)

```
/plugin marketplace add tjmode/koovi
```
```
/plugin install koovi@koovi
```

`/plugin` needs an interactive session. If it says it is not available here, such as in a remote
or web session, run the same thing from a terminal:

```sh
claude plugin marketplace add tjmode/koovi
claude plugin install koovi@koovi
```

**Codex, Cursor, or without the plugin system**

```sh
git clone https://github.com/tjmode/koovi.git
cd koovi && python3 install.py
```

Sets up every tool it finds. Add `--claude`, `--codex` or `--cursor` for one, `--uninstall` to
remove. Needs Python 3.8 or newer, nothing else.

**Updating** · `/plugin` in Claude Code shows when a new version is out, or run
`claude plugin update koovi` and restart. For the clone, `git pull` in the folder. Your settings
in `~/.koovi` are never touched by either.

> [!IMPORTANT]
> Koovi speaks on the machine where the session runs. Install it on the computer you sit at. In a
> cloud or web session it runs on a server with no speakers, so you would hear nothing.

## Commands

`/koovi <word>` in Claude Code, `./koovi.sh <word>` anywhere else.

| | |
| --- | --- |
| `status` | mode, muted projects, the last few decisions |
| `log 30` | why it spoke, or why it stayed quiet |
| `doctor` | check every part, and say what is missing |
| `quiet` | stop talking, flash the screen instead |
| `voice` · `auto` | talk again · talk only on headphones |
| `mute` · `unmute` | silence this project, or one you name |
| `test asking Payments "Postgres or SQLite?"` | hear a sample line |
| `voices` · `voice Daniel` | list voices · switch and hear one |
| `set rate 190` | change any setting, nested too: `set light.corner bottom-left` |

## When it stays quiet

- Turns under 5 seconds, so your "ok" replies never trigger it.
- Replies that ran no tools, unless they took over two minutes.
- The same window twice inside 20 seconds.
- Projects you muted, and your own quiet hours.
- After one reminder. Finished work is announced once and never nagged.

Questions and permission requests are always spoken, and it says what was asked. Two windows in
the same folder are told apart by what you asked for: *"Checkout, the fix the login bug session"*.

> [!TIP]
> Working in an office? `/koovi quiet` swaps the voice for a coloured frame that flashes around
> your screens for five seconds with the session named in the corner. `/koovi auto` picks by
> whether headphones are plugged in.

## Settings

One file, `~/.koovi/config.yaml`, written from [`config.example.yaml`](config.example.yaml) the
first time it runs. Every setting is explained next to its value there: the voice, what it calls
you, the phrases it can say, per-project names, and every timing rule. Edits apply to the next
announcement.

> [!NOTE]
> To turn music down in browser tabs, switch on **View > Developer > Allow JavaScript from Apple
> Events** in Brave or Chrome, or **Develop > Allow JavaScript from Apple Events** in Safari.
> Apple Music and Spotify need nothing.

## What it can see

Koovi reads the end of the current session's transcript to count tools and find the last question,
writes only to `~/.koovi`, and has no network code at all. It never replies to the coding tool,
never blocks a turn, and never touches your files. `koovi log` shows every decision it has made.

It also stays silent while your microphone is in use, and stops mid-word if the microphone opens
while it is talking.

## Platforms

macOS is in daily use. Windows and Linux are written but have not been tried on a real machine.
`koovi doctor` says what a given machine is missing. Reports from either are the most useful thing
you can send.

## Removing it

`/plugin uninstall koovi`, or `python3 install.py --uninstall`. Delete `~/.koovi` to drop your
settings and log as well.

---

Tests: `python3 -m unittest discover -s tests`. MIT licensed. [Changelog](CHANGELOG.md).
