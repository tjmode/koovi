---
name: set
description: Change a Koovi setting, for example rate 190 or user boss or light.corner bottom-left.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh set $ARGUMENTS
