---
name: dashboard
description: Show an activity and interruption summary across your coding sessions.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and show what it printed to the user. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh dashboard $ARGUMENTS
