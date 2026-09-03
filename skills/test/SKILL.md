---
name: test
description: Koovi: hear a sample line, for example /koovi:test asking Payments "Postgres or SQLite?"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *)
---

Run this command and tell the user, in one or two plain sentences, what it printed. Do nothing else.

    ${CLAUDE_PLUGIN_ROOT}/koovi.sh test $ARGUMENTS
