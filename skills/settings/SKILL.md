---
name: settings
description: See Koovi's main switches and change them by clicking. On or off, voice or screen light, quiet during calls, wait for research.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/koovi.sh *), AskUserQuestion
---

Show the user Koovi's main switches and change the ones they pick. Do nothing else.

1. Run this command:

       ${CLAUDE_PLUGIN_ROOT}/koovi.sh settings

   If it prints a line starting with ERROR, show that line to the user and stop.

2. Ask once, with the AskUserQuestion tool, all four questions in one call. In each question put the
   option that matches the current value first and add " (now)" to its label. Use these questions,
   headers and options, in this order:

   | Question | Header | Options, with the value each one sets |
   |---|---|---|
   | Koovi on or off? | Koovi | "On" sets `enabled true`; "Off" sets `enabled false` (never speaks or flashes) |
   | How should Koovi reach you? | Reach | "Voice" sets `mode voice` (speaks out loud); "Screen light" sets `mode quiet` (a coloured frame flashes, no sound); "Auto" sets `mode auto` (speaks on headphones, flashes on speakers) |
   | Stay quiet while the microphone is in use, in calls and dictation? | Calls | "Stay quiet" sets `wait_for_mic true`; "May talk" sets `wait_for_mic false` |
   | Wait for research agents to finish before saying done? | Research | "Wait" sets `wait_for_agents true`; "Don't wait" sets `wait_for_agents false` |

   Write each option's description in plain words, as given in brackets above.

3. For every answer that differs from the current value, run:

       ${CLAUDE_PLUGIN_ROOT}/koovi.sh set KEY VALUE

   Leave alone every answer that matches the current value. If the user typed their own answer,
   use it only when it clearly means one of the options; otherwise leave that setting alone.

4. Reply in one or two plain sentences: what changed, or that nothing changed. Then add this line:
   `/koovi:mute` silences this project, `/koovi:test` plays a sample line.

If the AskUserQuestion tool is not available, show what step 1 printed, then the `/koovi:set` line
that changes each switch (for example `/koovi:set enabled false`), and stop.
