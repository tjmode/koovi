---
name: koovi
description: Control Koovi, the voice that says which session finished or needs you. Use for status, voice, quiet, auto, mute, unmute, test, log, doctor, or set KEY VALUE.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and show the user what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh $ARGUMENTS

With no arguments, run `status` instead.

Words the user may pass:

- `status`: version, mode, screen light, muted projects, last decisions
- `voice`, `quiet`, `auto`: how Koovi reaches them. Talk, screen light only, or talk only on headphones
- `mute`, `unmute`: this project, or a folder name they give
- `test [done|asking|permission] [Project]`: hear a sample line
- `log [N]`: the diary of why it spoke or stayed quiet
- `doctor`: check the setup
- `set KEY VALUE`: change any setting, for example `set rate 190` or `set user boss`

Reply in one or two plain sentences. Do not edit files and do not run anything else.
