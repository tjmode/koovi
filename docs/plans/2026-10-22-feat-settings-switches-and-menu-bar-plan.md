---
title: "feat: Settings anyone can use (/koovi:settings now, a menu bar icon next)"
type: feat
status: active
date: 2026-10-22
---

# ✨ feat: Settings anyone can use

## Overview

People install Koovi and never find out that it can be switched off, made silent, or kept quiet
during calls. The switches exist, but only as lines in `~/.koovi/config.yaml` or as `/koovi:set`
commands you have to know by name. Tony's CEO could not tell whether "stay quiet in meetings" was on.

This plan adds two ways to see and flip the main switches, as in the mockup
(https://claude.ai/artifact/Hoei4B94EZu7g2LNHH4g3u):

1. **Phase 1, version 0.11.0: `/koovi:settings`.** One command inside Claude Code that shows the
   main switches as clickable choices. No app, nothing to install.
2. **Phase 2, version 0.12.0: a Koovi icon in the Mac menu bar.** On/off, how it reaches you,
   quiet during calls (with "right now: Zoom is using the mic"), wait for research, quiet hours,
   muted projects, test voice, all settings, diary.

The rule for both: **Python stays the brain.** Neither the command nor the menu writes the settings
file. Both read `koovi.sh settings` and change things with `koovi.sh set`, the same path as today.

## Problem Statement

What is missing today, checked in the code:

| # | Gap | Where |
|---|-----|-------|
| 1 | There is no on/off switch. `mode` is only voice, quiet (screen light) or auto | `DEFAULTS` and `voice_allowed()`, `koovi.py:1113` |
| 2 | Nothing shows all the main switches in one place. `/koovi:status` shows mode, light and muted projects, not calls or research | `cmd_status()`, `koovi.py:1763` |
| 3 | `koovi.sh set` writes any key and any value without checking, so a typo is saved silently | `cmd_set()`, `koovi.py:1747` |
| 4 | A reminder already waiting uses the settings from when it started, so a change (off, quiet mode) does not reach it for up to 2 minutes | `cmd_announce()` loads the config once, `koovi.py:1432`, then sleeps |
| 5 | A broken settings file silently falls back to defaults, so any screen would show the wrong values | `load_config()`, `koovi.py:277` |
| 6 | Two writers at once (menu, command, hand edit) can lose a change: read, change and write with no lock, and one shared `.tmp` name | `set_config_value()`, `koovi.py:1690`; `atomic_write()`, `koovi.py:323` |

## Proposed Solution

### Shared groundwork (ships in Phase 1)

**A. The on/off switch: `enabled: true`.**
- New key in `DEFAULTS` and `config.example.yaml`. A missing key means on, so old settings files keep working.
- When off: no voice, no screen light, no chime. Koovi still records prompts and session ends (so
  reminders and "you already replied" stay right), and still turns a lit screen light off. The diary says
  `quiet: Koovi is off`.
- Checked in `cmd_hook()` after the bookkeeping, before any `decide_*` call, next to the existing
  `proj["mute"]` check (`koovi.py:1415`). Switching off also clears any light that is showing.
- Never forgotten: `/koovi:status`, `/koovi:test` and `/koovi:doctor` start with `Koovi is OFF` when it is.

**B. Waiting reminders follow the current settings.** `cmd_announce()` reloads the settings before each
reminder and drops the reminder when Koovi is off. Mode and quiet hours are then also current.

**C. `koovi.sh settings`: one read for both screens.**
- Plain text for people and the skill:
  ```
  Koovi is ON · speaks out loud (voice)
  Stay quiet during calls: on   (right now: us.zoom.xos)
  Wait for research to finish: on
  Quiet hours: off
  Muted projects: none
  ```
- `koovi.sh settings --json` for the menu: `enabled`, `mode`, `wait_for_mic`, `wait_for_agents`,
  `quiet_hours`, `muted`, `recent_projects` (session folders in the state file, which keeps the last
  2 days, newest first), `mic` (who has the microphone, macOS only), `version`, `config_path`, and `error`.
- When the settings file cannot be read, `error` holds the reader's message (for example
  `cannot read line: 'mode voice'`). Both screens then show that and change nothing.

**D. `koovi.sh set` checks what it writes.**
- The key must exist in `DEFAULTS` (dot paths like `light.corner` included). If not: `unknown setting
  'enabeld'`, exit code 1.
- Known value types are checked: `enabled`, `wait_for_mic`, `wait_for_agents`, `focus_check`,
  `music_duck` and other true/false keys must be true or false. `mode` must be voice, quiet or auto.
  `quiet_hours.start` and `quiet_hours.end` must be HH:MM or empty. Numbers must be numbers.
- A settings file that does not read is never overwritten: say so and exit 1.
- Writes take a lock (`~/.koovi/config.lock`, the same `fcntl`/`msvcrt` locking `locked_state()`
  uses) around read, change and write, and use a temp file name unique to the process.

### Phase 1: `/koovi:settings` (0.11.0)

New skill `skills/settings/SKILL.md`, the same pattern as the other nine:

```markdown
---
name: settings
description: See Koovi's main switches and change them by clicking. On or off, voice or screen light, quiet during calls, wait for research.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *), AskUserQuestion
---
```

What the skill tells Claude to do:

1. Run `${CLAUDE_PLUGIN_ROOT}/koovi.sh settings`. If it prints an error line, show it and stop.
2. Ask **once**, with four questions in one AskUserQuestion call. Each question puts the current value
   first, marked `(now)`:

   | Question | Header | Options | Setting |
   |---|---|---|---|
   | Koovi on or off? | Koovi | On / Off | `enabled` |
   | How should it reach you? | Reach | Voice / Screen light / Auto (voice on headphones, light on speakers) | `mode` voice / quiet / auto |
   | Stay quiet while the mic is in use (calls, dictation)? | Calls | Stay quiet / May talk | `wait_for_mic` |
   | Wait for research agents before saying "done"? | Research | Wait / Don't wait | `wait_for_agents` |

3. For every answer that differs from the current value, run `koovi.sh set KEY VALUE`. Answers equal
   to the current value change nothing, so keeping all four is the way to cancel. A free-text "Other"
   answer is used only if it clearly names one of the listed values; otherwise that setting is left alone.
4. Reply in one or two plain sentences: what changed, or "nothing changed". Then one line:
   `/koovi:mute` silences this project, `/koovi:test` plays a sample.
5. When the question tool is not available (a non-interactive `claude -p` run), print the settings
   and the `/koovi:set` lines that would change each one, and stop.

Why four questions and not the seven-line list in the mockup: the question tool allows 1 to 4
questions per call and 2 to 4 options per question (checked in the tool's own definition). Four
questions with their current values fits in one screen and covers what people need. Mute and test
keep their own commands.

Also in Phase 1:
- README: `/koovi:settings` goes first in the commands table, as the one to remember.
- The mockup's right frame is redrawn to show the four-question form as it will really look.

### Phase 2: menu bar icon (0.12.0, macOS only)

A second Swift helper, `menu/KooviMenu.swift`, built and shipped the same way as the screen light:
one file, `xcrun swiftc -O`, no Xcode project, no app bundle, a universal binary shipped as
`menu/koovi-menu`, and a fallback build into `~/.koovi/bin/koovi-menu` when the shipped one cannot
run (copy of the `light_commands()` logic, `koovi.py:1172`).

**Proven on this Mac (macOS 26.5.1), 2026-10-22:** a bare swiftc binary with
`setActivationPolicy(.accessory)` and an SF Symbol template image shows an icon in the menu bar when
started from Python with `Popen(start_new_session=True)`. Screenshots with the test running and after
it was killed show the icon only in the first. Opening the menu and clicking a switch in it were
**not** tested yet.

**How it finds Koovi after updates.** The plugin folder changes with every version
(`~/.claude/plugins/cache/koovi/koovi/<version>/`). So each hook writes a two-line shim
`~/.koovi/bin/koovi` (`exec "<current folder>/koovi.sh" "$@"`), only when the folder changed. The menu
only ever runs the shim. When `settings --json` reports a version different from the one the menu was
built for, the menu quits and the next hook starts the new one.

**Who starts it.**
- Hooks start it the same way as the screen light, if it is not already running (one copy at a time,
  `flock` on `~/.koovi/menu.lock`).
- New setting `menu_bar: true` (macOS). "Hide Koovi from the menu bar" in the menu sets it to false
  and quits. It comes back with `/koovi:settings` or `/koovi:set menu_bar true`. So quitting is
  remembered, and hooks do not bring it straight back.
- "Start at login" is a checkmark in the menu, off by default. It writes a LaunchAgent at
  `~/Library/LaunchAgents/com.tjmode.koovi.menu.plist` that runs `~/.koovi/bin/koovi menu-start`.
  macOS shows a "Background item added" note the first time (reported; to be confirmed on 26).

**What the menu shows** (left frame of the mockup):

| Item | Does | Through |
|---|---|---|
| Koovi, status line, on/off | `On. Speaks out loud.` / `Off. Silent everywhere.` Off greys out the rest | `set enabled` |
| How it reaches you | Voice / Screen light / Auto, one line of explanation below | `set mode` |
| Stay quiet during calls | with `Right now: Zoom is using the mic`, or `Right now: nothing` | `set wait_for_mic`, `mic` field |
| Wait for research to finish | | `set wait_for_agents` |
| Quiet hours › | Off · 22:00 to 07:00 · 23:00 to 08:00 · Custom (opens settings) | `set quiet_hours.start/end` |
| Muted projects › | Recent projects with a checkmark when muted | `koovi mute NAME` / `unmute NAME` |
| Test voice | Plays a sample line, then shows the last thing Koovi said | `koovi test` |
| All settings… | Opens `config.yaml` in the default text editor (`open -t`) | |
| What did Koovi do? | Opens the diary `~/.koovi/koovi.log` | |
| Start at login | Checkmark | LaunchAgent |
| Hide from menu bar | | `set menu_bar false`, quit |

- Icon: SF Symbol `waveform` as a template image, `waveform.slash` when Koovi is off, so off can be
  seen without opening anything.
- **Muted projects come from the state file, not the current folder.** The menu has no working folder,
  and `cmd_mute` without a name would mute the menu's own folder (`Path.cwd().name`,
  `koovi.py:1757`). The menu always passes the name.
- Staying light: no timer while closed. When the menu opens it shows the last values at once, runs
  `settings --json` in the background, and updates when it returns, so the menu never freezes. While
  open, the mic line refreshes every 2 seconds. One mic check costs about 16 ms (measured 2026-10-20).
- **Switches: start with plain menu items** (checkmarks and a three-way choice), which macOS draws,
  highlights and lets you use from the keyboard. The mockup's toggle switches need custom views in the
  menu. Apple's docs say a view item draws nothing for you (no highlight, no checkmark). Build those
  only if Step 1 of Phase 2 shows they work and feel right.

## Technical Considerations

- **Gatekeeper.** The shipped screen light binary is ad-hoc signed (`codesign` shows
  `adhoc,linker-signed`; `spctl` rejects it) and still runs because Koovi starts it itself, and files
  from `git clone` carry no quarantine flag. The menu binary is in the same position. Not verified for
  a binary that arrives through the plugin installer on macOS 26: the fallback build covers it.
- **macOS 26 "Allow in the Menu Bar".** System Settings › Menu Bar has a per-app switch that can hide
  an icon. Whether new items start hidden, and what name a bare binary shows there, are **not verified**.
  On MacBooks with a notch, extra icons can hide behind it. Answer: `/koovi:doctor` says
  "menu bar icon running" and, if you cannot see it, where to look. The README says the same.
- **The window list cannot see status items on macOS 26** (they belong to Control Center there), so
  "is the menu running" is checked with the lock file, never the window list.
- **Windows and Linux.** Phase 1 works everywhere Claude Code runs. "Auto" and the mic check on
  Windows and Linux are written but untested, as today; the skill does not hide them. Phase 2 is macOS only.
- **No new packages.** Python stays standard library; Swift stays one file with AppKit.

## Acceptance Criteria

### Groundwork and Phase 1
- [x] `enabled: false` stops every voice, light and chime from hooks and from waiting reminders; the
      diary says `quiet: Koovi is off`; prompts and session ends are still recorded
- [x] Turning off clears a screen light that is showing
- [x] A reminder waiting when Koovi is turned off never speaks (test with a short `reminder_after_seconds`)
- [x] `status`, `test` and `doctor` start with `Koovi is OFF` when off
- [x] `koovi.sh settings` and `settings --json` print the values above; a broken settings file gives
      `error` and both screens refuse to write
- [x] `koovi.sh set` rejects unknown keys and bad values with exit code 1, and never writes over a
      settings file it cannot read
- [x] Two `set` calls at the same moment both land (lock test)
- [ ] `/koovi:settings` asks once with four questions, current value first; changes only what differs;
      falls back to printed commands when the question tool is missing
      (skill written; a live run in Claude Code is still to do: `claude --plugin-dir .` then `/koovi:settings`)
- [x] Settings example, `DEFAULTS` and the defaults-match test include `enabled` (and `menu_bar` in Phase 2)
- [x] README, CHANGELOG, version 0.11.0 in `koovi.py`, `plugin.json`, `marketplace.json`, README badge
- [x] Mockup right frame updated to the four-question form

### Phase 2
- [x] Step 1 spike: menu opens, a checkmark item and a view item with a switch both respond to clicks,
      from a bare swiftc binary started by Python (2026-10-22: built with plain checkmark items, so no
      view items were needed; the menu opened from Python and was screenshotted on the second display)
- [x] Every row of the menu table works and changes the file only through `koovi set` / `mute`
      (`koovi-menu --selftest` against a fake Koovi pressed every item: 18 commands, all valid)
- [ ] Icon shows `waveform.slash` when off; status line matches `/koovi:status`
- [ ] Mic line names the app during a real call, "nothing" otherwise
- [x] After a plugin update the old menu quits and the new one starts on the next hook (end-to-end, throwaway home)
- [x] "Hide from menu bar" stays hidden across hooks until turned back on (end-to-end)
- [ ] Start at login works after a restart and shows in System Settings › Login Items
      (the LaunchAgent is written and removed correctly; a real restart is not verified)
- [x] CI builds `menu/KooviMenu.swift` like it builds the light helper (step added; runs on the next push)
- [x] Idle CPU of the menu process about 0 with the menu closed (0.01 s over 20 s, 46 MB)
- [ ] Manual check on a Mac with a notch and many icons, and with the icon switched off under
      "Allow in the Menu Bar"
- [ ] Open bug, cause proven, waiting for Tony's go: `menu-start` treats a deliberate stop
      (`koovi menu hide` within its 1.5 s start check) as a failed start and builds a fallback copy,
      which then quits because the icon is hidden. Proof: diary line "stopped by SIGTERM from pid 38408",
      the `menu hide` run right after icon 38407. Fix: after a failed start, stop if `menu_bar` is false
      or the exit was SIGTERM

## Success Metrics

- Tony's CEO can say whether "stay quiet during calls" is on, and change it, without help.
- No more "how do I turn it off" questions in Discord.
- The diary shows `quiet: Koovi is off` lines from more than one person within the first week.

## Dependencies & Risks

| Risk | Answer |
|---|---|
| Someone turns Koovi off and forgets | Off icon in the menu bar; `Koovi is OFF` at the top of status, test and doctor. A timed "off for 1 hour" is left for later |
| macOS hides the icon (Allow in the Menu Bar, notch) | Doctor and README say where to look; `/koovi:settings` works without the icon |
| Custom switch views misbehave in a menu | Plain checkmark items first; switches only after the spike |
| The plugin installer quarantines the binary on some Mac | Fallback build into `~/.koovi/bin`, as the screen light does |
| A stricter `set` breaks someone's existing `/koovi:set` habit | Only keys not in `DEFAULTS` and wrong value types are refused, with a message naming the key |
| `wait_for_agents` and mute keyed by folder name: two projects with the same folder name share a mute | Unchanged from today; written in the README |

## Files

**Phase 1**
- `koovi.py`: `DEFAULTS` (`enabled`), `cmd_hook` (off check), `cmd_announce` (reload per reminder),
  new `cmd_settings` and the `settings` dispatch, `cmd_set` (checks), `set_config_value` and
  `set_project_mute` (lock, refuse broken file), `atomic_write` (unique temp name), `cmd_status`,
  `cmd_test`, `cmd_doctor` (OFF line)
- `skills/settings/SKILL.md` (new)
- `config.example.yaml`, `tests/test_koovi.py`, `README.md`, `CHANGELOG.md`, `.claude-plugin/*.json`

**Phase 2**
- `menu/KooviMenu.swift`, `menu/koovi-menu` (new)
- `koovi.py`: shim writer, `menu_commands()` / `cmd_menu_start()` (like the light helper), `menu_bar`
  default, doctor line, LaunchAgent write and remove
- `.github/workflows/*`: build step; `README.md`, `CHANGELOG.md`, version 0.12.0

## References & Research

- Mockup: https://claude.ai/artifact/Hoei4B94EZu7g2LNHH4g3u
- Existing skill pattern: `skills/set/SKILL.md`, `skills/mute/SKILL.md`
- Screen light helper to copy: `light/KooviLight.swift`, `light_commands()` `koovi.py:1172`,
  `cmd_light_start()` `koovi.py:1222`
- Status item from a bare binary, tested here: scratchpad `sitest/T.swift`, screenshots `c1.png`, `c2.png`
- NSMenuItem.view draws nothing for you: https://developer.apple.com/documentation/appkit/nsmenuitem/view
- menuNeedsUpdate: https://developer.apple.com/documentation/appkit/nsmenudelegate/menuneedsupdate(_:)
- SMAppService.agent needs an app bundle: https://developer.apple.com/documentation/servicemanagement/smappservice/agent(plistname:)
- Login and background items since Ventura: https://eclecticlight.co/2023/02/15/controlling-login-and-background-items-in-ventura/
- Allow in the Menu Bar (macOS 26): https://support.apple.com/guide/mac-help/change-menu-bar-settings-mchlad96d366/26/mac/26
- Icons hidden by the notch: https://talk.tidbits.com/t/macbook-pro-menu-bar-apps-and-the-notch/22085
- Quarantine and ad-hoc signing: https://developer.apple.com/forums/thread/757647,
  https://eclecticlight.co/2023/05/10/how-macos-now-tracks-the-provenance-of-apps/
