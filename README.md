# Koovi

Koovi says which of your coding sessions just finished or needs an answer, so you can work in one
window while three others run.

```
"Koovi reporting, boss. Checkout is done."
"Payments is asking: should we use Postgres or SQLite?"
```

One line, one reminder if you do not reply, then silence. Your next message in that window counts
as the answer.

Works with Claude Code, Codex and Cursor, at the same time. Written for macOS; Windows and Linux
are in the code but have not been tried on a real machine.

Koovi is Tamil for "call out".

## Install

Claude Code:

```
/plugin marketplace add tjmode/koovi
/plugin install koovi@koovi
```

Codex, Cursor, or Claude Code without the plugin system:

```
git clone https://github.com/tjmode/koovi.git
cd koovi && python3 install.py
```

`install.py` sets up every tool it finds: `~/.claude/settings.json`, `~/.codex/hooks.json`,
`~/.cursor/hooks.json`. Pick one with `--claude`, `--codex`, `--cursor`. Remove with
`--uninstall`. Each file is copied to a `.bak-koovi-*` backup first.

Needs Python 3.8 or newer. Nothing else, no packages.

## Commands

In Claude Code type `/koovi <word>`. Anywhere else run `./koovi.sh <word>`.

| Command | What it does |
| --- | --- |
| `status` | version, mode, what the light shows, muted projects, last three decisions |
| `log [n]` | the last n decisions and why each was made (default 30) |
| `doctor` | checks every part and names what is missing |
| `voice` / `quiet` / `auto` | talk, screen light only, or talk only on headphones |
| `mute [folder]` / `unmute [folder]` | silence one project; no folder means the one you are in |
| `set KEY VALUE` | change any setting, including nested ones: `set light.corner bottom-left` |
| `voices` / `voice NAME` | list the voices on this machine, or switch and hear a sample |
| `test [kind] [project] [question]` | hear a line: `test asking Payments "Postgres or SQLite?"` |
| `light` / `light test` / `light off` | what the light shows, a demo flash, clear it |
| `mic` | is anything recording right now |
| `version` | which version is running |

## When it speaks

| Situation | What happens |
| --- | --- |
| Turn under 5 seconds | silent, so your "ok" replies never trigger it |
| Reply with no tools, under 2 minutes | silent |
| Reply ending in a question | spoken, with the question itself when it can be read |
| Permission request | spoken, even if you are looking at that window |
| Real work finished | spoken once, never repeated |
| A second project finishing within 30 seconds | a shorter "also done" line |
| Same window twice within 20 seconds | the second is dropped |
| A subagent finishing | diary only, so one turn is one announcement |
| No reply after 2 minutes | one reminder, for questions and permissions only |
| You reply in that window | the reminder is cancelled |

Two windows in the same folder are told apart by what you asked for: *"Checkout, the fix the login
bug session"*. `/rename` a window and Koovi uses that name instead.

## Settings

One file, `~/.koovi/config.yaml`, created from `config.example.yaml` the first time Koovi runs.
Edits take effect on the next announcement. `koovi set` edits it for you and keeps the comments.

| Key | Default | Meaning |
| --- | --- | --- |
| `assistant` | `Koovi` | what the voice calls itself |
| `user` | `boss` | what it calls you |
| `voice` | `Samantha` | any voice from `koovi voices` |
| `rate` | `175` | words per minute |
| `chime` | Glass.aiff | sound used instead of the voice during quiet hours |
| `mode` | `voice` | `voice`, `quiet` (light only), `auto` (voice on headphones) |
| `focus_check` | `false` | `true` plays the chime instead of talking when you are on that window |
| `permission_always_speak` | `true` | permission requests are spoken even then |
| `always_announce_questions` | `true` | a question is spoken even after a short turn |
| `wait_for_background_tasks` | `false` | `true` waits for background jobs before saying done; only for short jobs |
| `remind_for` | `[asking, permission]` | which kinds get the one reminder |
| `music_duck` / `music_duck_percent` | `true` / `20` | turn music down to this while talking |
| `browser_music_sites` | youtube, soundcloud, spotify, apple music | tabs treated as music |
| `wait_for_mic` | `true` | never talk over dictation or a call |
| `mic_wait_max_seconds` | `120` | after this, play the chime instead |
| `mic_settle_seconds` | `1.5` | pause after the mic closes before talking |
| `quiet_hours.start` / `.end` | empty | chime only between these times |
| `timing.min_task_seconds` | `5` | shorter turns are never announced |
| `timing.chat_needs_seconds` | `120` | a reply with no tools must run this long to count |
| `timing.reminder_after_seconds` | `120` | how long before the reminder |
| `timing.reminders` | `1` | how many reminders; `0` turns them off |
| `timing.debounce_seconds` | `20` | never speak twice for one window inside this |
| `timing.also_done_window_seconds` | `30` | a second "done" inside this uses the shorter line |
| `light.enabled` | `true` | the screen light |
| `light.when` | `instead_of_voice` | or `always`, to flash while talking too |
| `light.seconds` | `5` | how long one flash lasts |
| `light.corner` | `top-right` | where the session is named |
| `light.pulse` | `true` | blink |
| `light.colors` / `light.labels` | red and orange | per kind: done, asking, permission, reminder |
| `projects` | empty | spoken name and mute flag per folder |
| `phrases` | six done lines, seven asking lines, and so on | the lines it can say |

Phrases take `{assistant}`, `{user}`, `{project}` and `{question}`. Lines containing `{question}`
are used only when a question could be read, so keep plain ones as a fallback:

```yaml
projects:
  checkout-web:     Checkout
  payments-backend: { say: "Payments backend" }
  scratch:          { mute: true }

phrases:
  asking:
    - "{user}, {project} is asking: {question}"
    - "{project} needs you."
```

## The screen light

`koovi quiet` stops all sound. Instead a coloured frame blinks around every screen for five
seconds with the session named in a corner: *"Checkout  done"*, *"Payments  needs an answer"*.
Clicks pass through it, and it follows the same ladder as the voice: one flash, one reminder
flash, then nothing.

`koovi auto` decides for you, by whether headphones are the output.

The light is a small helper in `light/`, shipped prebuilt for Intel and Apple silicon. It starts
when needed and quits when idle. If the shipped copy will not run, Koovi builds a new one with
Xcode's command line tools.

## Music and the microphone

Koovi turns Apple Music, Spotify and browser music tabs down to 20 percent while it talks, then
puts them back. Browser tabs need one setting turned on by hand:

- Brave and Chrome: View > Developer > Allow JavaScript from Apple Events
- Safari: Develop > Allow JavaScript from Apple Events

If anything is recording, Koovi waits. If the microphone opens while it is talking, it stops
mid-word and says the line again once the microphone is free. That exists because dictation kept
picking up the voice.

## Platform support

| | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Voice | `say` | built-in speech | `spd-say`, `espeak-ng` or `festival` |
| Chime | `afplay` | a beep | `paplay` or `aplay` |
| Which window is in front | yes | yes | needs `xdotool` |
| Microphone in use | yes | yes | yes, via ALSA |
| Music turned down | yes | no | no |
| Screen light | yes | first draft | no, the voice is used |
| Headphones, for `auto` | yes | cannot tell, so it talks | cannot tell, so it talks |

On Linux install a speech program first: `sudo apt install speech-dispatcher`. Run `koovi doctor`
anywhere and it lists what is missing.

## What it can see and do

- Reads the end of the current session's transcript to count tools and find the last question.
- Runs `say`, `afplay` and AppleScript locally. The AppleScript sets the volume of music apps and,
  if you turn on the setting above, of browser tabs.
- Starts a background process to speak, and the light helper when the light is on.
- Writes only to `~/.koovi`: your settings, session state, and the decision log.
- Has no network code. Nothing leaves your machine.
- Never replies to the coding tool, never blocks a turn, never touches your files.

`koovi log` shows every decision it has made and the reason for it.

## Removing it

```
/plugin uninstall koovi
```

or `python3 install.py --uninstall` for the script install. Delete `~/.koovi` to remove your
settings and log too.

## Working on it

```
python3 -m unittest discover -s tests
```

36 tests, no sound, nothing touched outside a temporary folder. They cover the settings reader,
the transcript readers for Claude Code and Codex, every decision rule, the platform commands and
the plugin files. `koovi.py` is one file on purpose.

To try a change as a plugin, bump the version in `.claude-plugin/plugin.json` and
`marketplace.json`, then reinstall. Plugins are pinned to their version, so an unchanged number
keeps the old copy running.

Help most wanted: someone with a Windows or Linux machine to say what breaks, turning music down
on those systems, and better voices than the built-in ones.

## Licence

MIT.
