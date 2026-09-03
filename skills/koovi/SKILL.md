---
name: koovi
description: Run any other Koovi command, such as auto, light, voices, mic or version.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh $ARGUMENTS
