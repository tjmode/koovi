---
name: status
description: Show how Koovi is set right now, what is on the screen light, which projects are muted, and the last few decisions.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh status
