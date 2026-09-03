---
name: unmute
description: Let a muted project speak again. With no argument it means the project you are in.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh unmute $ARGUMENTS
