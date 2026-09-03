# Koovi

You have four Claude Code windows open. One just finished, another is waiting on an answer,
and you are looking at a different screen. Koovi tells you which one, out loud:

> "Koovi reporting, boss. Payments is done."
> "Checkout is asking: should we use Postgres or SQLite?"

Then it stops. One line, one reminder if you still have not replied, and nothing more.
No badge to clear, no list to manage.

Koovi is Tamil for "call out". The name of the voice is yours to change.

Works with Claude Code, Codex and Cursor.

macOS is the version in daily use. Windows and Linux are written and shipped but have not been
tried on a real machine yet, so treat them as a first draft and please report what breaks.

## Install

**In Claude Code**, two commands:

```
/plugin marketplace add tjmode/koovi
/plugin install koovi@koovi
```

**For Codex or Cursor**, or if you would rather not use the plugin system:

```
git clone https://github.com/tjmode/koovi.git
cd koovi && python3 install.py
```

That sets up every tool it finds on your machine: `~/.claude/settings.json`, `~/.codex/hooks.json`
and `~/.cursor/hooks.json`. Name one with `--claude`, `--codex` or `--cursor`. Undo it all with
`python3 install.py --uninstall`. Each file is backed up before it is touched.

One Koovi serves all three at once, so a Codex window and a Claude Code window are told apart by
name just like two Claude Code windows are.

Nothing to install besides Python 3.8 or newer, which your Mac already has.

## Use it

Everything runs through one command inside Claude Code:

```
/koovi status          how it is set, and the last few decisions
/koovi quiet           stop talking, use the screen light instead
/koovi voice           talk again
/koovi auto            talk only when headphones are on
/koovi mute            silence this project
/koovi test asking     hear a sample line
/koovi log 30          why it spoke, or why it stayed quiet
/koovi doctor          check the setup
/koovi set rate 190    change any setting
```

From a terminal, the same words work: `./koovi.sh status`.

## Your settings

One file, `~/.koovi/config.yaml`. It reads like a note, and Koovi picks up changes on the next
announcement. The version in this repo is `config.example.yaml`; your copy is made from it the
first time Koovi runs.

Worth knowing:

- `assistant` and `user`: what the voice calls itself and what it calls you.
- `voice` and `rate`: any Mac voice. `/koovi voices` lists them.
- `projects`: the spoken name for each folder, and which ones to keep silent.
- `phrases`: the lines it can say. Add your own. Blanks: `{assistant}` `{user}` `{project}` `{question}`.
- `timing`: how long a turn must run before it counts, and how long before the one reminder.

## When it speaks, and when it does not

- Short turn, under five seconds: quiet. Your "OK" replies never trigger it.
- A reply that ran no tools: quiet, unless it took over two minutes.
- A question for you: always spoken, and Koovi says the question itself when it can read one.
- A permission request: always spoken. That one blocks the session.
- Background work still running: announced as usual. The wake-up message itself never counts as
  your reply. Set `wait_for_background_tasks: true` to stay quiet until that work wakes the
  session instead, which only suits short background jobs.
- A subagent finishing: diary only. The session speaks when it is really done.
- Two projects finishing together: the second gets a shorter "also done" line.
- Anything else: one line. A question or permission request gets one reminder after two minutes,
  then silence. Finished work is never repeated.
- Your next message in that window is the answer. It cancels the reminder.

Two windows in the same folder are told apart by what you asked for: "Checkout, the fix the login
bug session". Name a window yourself with `/rename` and Koovi uses that instead.

## Quiet mode, for an office

```
/koovi quiet
```

No sound at all. Instead a coloured frame blinks along the edges of every screen for five
seconds, with the session named in a corner: "Checkout  done", "Payments  needs an answer". Clicks
pass straight through it. Same ladder as the voice: one flash, one reminder flash, then gone.

`/koovi auto` picks for you: the voice when headphones or AirPods are the output, the light when
sound would come out of the speakers.

The light is a small helper program in `light/`, shipped prebuilt for both kinds of Mac. It
starts when needed and quits when nothing is waiting. If the shipped copy cannot run, Koovi
builds a fresh one with Xcode's command line tools.

## Windows and Linux

The rules are the same everywhere. What changes is how the machine is asked to do things:

| | macOS | Windows | Linux |
| --- | --- | --- | --- |
| Voice | `say` | built-in speech | `spd-say`, `espeak-ng` or `festival` |
| Sound | `afplay` | a short beep | `paplay` or `aplay` |
| Which window is in front | yes | yes | needs `xdotool` |
| Is the microphone in use | yes | yes | yes, through ALSA |
| Turn music down | yes | not yet | not yet |
| Screen light | yes | yes, a first draft | not yet, the voice is used |
| Headphones for auto mode | yes | cannot tell, so it talks | cannot tell, so it talks |

On Linux, install a speech program first: `sudo apt install speech-dispatcher`. Run
`/koovi doctor` on any machine and it says exactly what is missing.

## Music and the microphone

While Koovi talks it turns Apple Music, Spotify and browser music tabs down to 20 percent, then
puts them back. Browser tabs need a one-time setting: in Brave or Chrome, View > Developer >
Allow JavaScript from Apple Events. In Safari, Develop > Allow JavaScript from Apple Events.

If any app is using the microphone, for dictation or a call, Koovi waits. If the microphone
opens while it is already talking, it stops mid-word and says the line again once you are done.

## What Koovi can see and do

Worth knowing before you install anything that runs on every turn:

- It reads the tail of the current session's transcript file to count tool uses and find the last
  question. Nothing is sent anywhere. There is no network code in Koovi at all.
- It runs `say`, `afplay` and AppleScript locally. The AppleScript reaches into music apps and,
  if you switch on the setting above, into browser tabs to set their volume.
- It starts a small background process to speak, and the screen light helper when the light is on.
- It writes to `~/.koovi` only: your settings, the session state, and the diary of decisions.
- It never talks back to Claude Code, never blocks a turn, and never touches your code.

Read `/koovi log` any time to see every decision it made and why.

## Remove it

```
/plugin uninstall koovi
```

or, for the script install, `python3 install.py --uninstall`. Then delete `~/.koovi` if you want
your settings and diary gone too.

## Help wanted

- Trying Koovi on Windows and on Linux, and telling us what broke. The code is there; the
  testing is not.
- Turning music down on Windows and Linux.
- Better voices than the built-in ones.
- Cursor writes no transcript Koovi can read yet, so it cannot say what a Cursor session asked.
  Everything else works there.

Tests: `python3 -m unittest discover -s tests`. They never make a sound and never touch `~/.koovi`.

MIT licensed. Issues and pull requests welcome.
