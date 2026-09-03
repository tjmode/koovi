# Koovi

[![tests](https://github.com/tjmode/koovi/actions/workflows/ci.yml/badge.svg)](https://github.com/tjmode/koovi/actions/workflows/ci.yml)
[![version](https://img.shields.io/badge/version-0.9.9-2ea44f)](CHANGELOG.md)
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

## Install

**Claude Code** (one line at a time)

```
/plugin marketplace add tjmode/koovi
```
```
/plugin install koovi@koovi
```

**Codex, Cursor, or a terminal**

```sh
git clone https://github.com/tjmode/koovi.git
cd koovi && python3 install.py
```

Needs Python 3.8 or newer, nothing else. Update with `claude plugin update koovi`, or `git pull`,
then restart. Your settings survive.

> [!IMPORTANT]
> Koovi speaks on the machine that runs the session. Install it on the computer you sit at, not in
> a cloud or web session, where nobody can hear it.

## Commands

Type `/koovi:` in Claude Code and they all appear. The same words work after `./koovi.sh`.

| Command | What it does |
| :--- | :--- |
| `/koovi:status` | how it is set, and the last few decisions |
| `/koovi:log` | why it spoke, or why it stayed quiet |
| `/koovi:doctor` | check every part, and name what is missing |
| `/koovi:quiet` | stop talking, flash the screen instead |
| `/koovi:voice` | talk again, or add a name to switch voice |
| `/koovi:mute` | silence this project, `/koovi:unmute` to undo |
| `/koovi:test` | hear a sample line |
| `/koovi:set` | change one setting |
| `/koovi:koovi` | anything else: `auto`, `light`, `voices`, `mic`, `version` |

Nothing about the voice is fixed:

```sh
/koovi:set assistant Jarvis      # what it calls itself
/koovi:set user boss             # what it calls you
/koovi:voice Daniel              # which voice speaks
/koovi:set rate 190              # how fast
```

## When it stays quiet

- Turns under 5 seconds, so your "ok" replies never trigger it.
- Replies that ran no tools, unless they took over two minutes.
- The same window twice inside 20 seconds, muted projects, and your quiet hours.
- After one reminder. Finished work is announced once and never nagged.
- While your microphone is in use. It even stops mid-word if you start dictating.

Questions and permission requests are always spoken, and it says what was asked.

> [!TIP]
> In an office? `/koovi:quiet` swaps the voice for a coloured frame that flashes around your
> screens for five seconds with the session named in the corner. `/koovi:koovi auto` picks by
> whether headphones are plugged in.

## Good to know

- Everything is in `~/.koovi/config.yaml`, explained line by line inside
  [`config.example.yaml`](config.example.yaml): the sentences it says, per-project names, timings.
- It reads the end of the session transcript, writes only to `~/.koovi`, and has no network code.
  Nothing leaves your machine. `/koovi:log` shows every decision it ever made.
- macOS is in daily use. Windows and Linux are written but untested, and `/koovi:doctor` says what
  a machine is missing. Reports from either are the most useful thing you can send.
- Remove it with `/plugin uninstall koovi`, or `python3 install.py --uninstall`.

Something unclear or broken? Run `/koovi:doctor`, then
[open an issue](https://github.com/tjmode/koovi/issues).

---

MIT licensed · [Changelog](CHANGELOG.md) · tests: `python3 -m unittest discover -s tests`
