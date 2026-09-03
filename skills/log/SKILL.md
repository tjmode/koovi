---
name: log
description: Show Koovi's recent decisions and why each one was made. Takes a number of lines, 30 by default.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh log $ARGUMENTS
