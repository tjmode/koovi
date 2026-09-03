---
name: mute
description: Koovi: silence one project. No argument means the project you are in. Undo with /koovi:unmute.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh mute $ARGUMENTS
