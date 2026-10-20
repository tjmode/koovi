---
title: "fix: Never speak into a call (reliable mic and meeting detection on macOS)"
type: fix
status: active
date: 2026-10-20
---

# 🐛 fix: Never speak into a call

## Overview

Koovi is supposed to stay quiet while the microphone is in use (dictation, calls). A user wearing
headphones in a meeting heard Koovi talk over the other people. The setting `wait_for_mic` is on by
default, so this is a detection bug, not a configuration problem.

Today `mic_in_use()` on macOS asks CoreAudio whether a *device* is running. Research and tests on a
real Mac show that this question is the wrong one in four different ways. This plan switches the
primary signal to "which app is recording right now", keeps the device check only as a fallback,
and adds a short memory so a muted call is still treated as a call.

## Problem Statement

What happens now, and where each claim was checked:

| # | Problem | Effect | Evidence |
|---|---------|--------|----------|
| 1 | Only the **default** input device was checked | Call app records from the headset mic, default is the idle built-in mic, so Koovi speaks | Reproduced on this Mac: recording from a non-default device gave `mic_in_use() = False`. A first fix in the working tree now checks every input device |
| 2 | `kAudioDevicePropertyDeviceIsRunningSomewhere` ('gone') is **device-wide** | A device with both input and output (USB headset, BlackHole, some docks) reads "mic busy" when it only *plays* sound. Music, or Koovi's own voice, can look like a call | SDK header text (no scope); measured here: `say -a "BlackHole 16ch"` set 'gone' = 1 with nobody recording |
| 3 | Bluetooth mics may **never** report 'gone' | AirPods calls missed entirely | Single report, Apple engineer acknowledged, no fix posted ([forums/741026](https://developer.apple.com/forums/thread/741026)). **Not verified** on hardware here |
| 4 | Web calls on **mute** release the mic (browser-level mute) | Muted in Google Meet, Koovi talks in your ear while others speak | PETS 2022 study ([paper](https://ar5iv.labs.arxiv.org/html/2204.06128)); native apps (Zoom, Teams, Slack, Discord) mostly keep the mic open on mute. Current 2026 app versions **not verified** |
| 5 | The diary never says **which app** holds the mic | Cannot tell real calls from false positives | `~/.koovi/koovi.log`: 222 "microphone in use", 164 "still busy after the wait", 13 "opened mid-sentence". Cause of each **not verified** |

## Proposed Solution

Three layers, checked in this order, inside `mic_in_use()` (`koovi.py`, the "microphone" section).

### Layer 1: per-app recording (primary)

CoreAudio process objects (macOS 14.2+, per two sources; Apple gives no version, so treat any read
error as "unavailable" and fall to layer 2):

- `kAudioHardwarePropertyProcessObjectList` ('prs#') on the system object: all audio client processes
- per process: `kAudioProcessPropertyIsRunningInput` ('piri'), `kAudioProcessPropertyBundleID` ('pbid'),
  `kAudioProcessPropertyPID` ('ppid')

Busy when any process has `piri = 1`, except:

- `com.apple.CoreSpeech` ("Hey Siri" listener; seen on this Mac with `piri = 1` all the time)
- `historicalaudiod` (reports input with an empty bundle ID; reported in [Sapphire #176](https://github.com/cshariq/Sapphire/issues/176)). Match by process name via `proc_name()` from libproc, because the bundle ID is empty
- Koovi's own PID and its speech child (`say`)
- anything in a new setting `mic_ignore_apps` (bundle IDs or process names), for always-on tools like Krisp

Dictation apps (Voibe, Elephas, macOS dictation) stay counted as busy. That is the existing intent:
never talk over dictation.

Verified on this Mac (macOS 26.5.1): playing into BlackHole gave `piri = 0, piro = 1`; recording from it
gave `piri = 1`. Device-wide confusion (problem 2) is gone, and Bluetooth (problem 3) does not depend
on 'gone'. No permission prompt is expected (reported by several projects); confirm on first run.

### Layer 2: device check (fallback only)

Used only when layer 1 is unavailable (older macOS, read error). It is the current working-tree code,
narrowed: every input device **except** virtual and aggregate ones (`kAudioDevicePropertyTransportType`
'tran' = 'virt' or 'grup'), since BlackHole, Loopback and Krisp-style devices can run permanently.

### Layer 3: call memory (muted calls)

When layer 1 sees a **call app** recording, remember it: `{"app": bundle_id, "pid": pid, "at": now}` in
`state.json`. For the next `call_grace_seconds` (default 600), treat the mic as busy while that same
process still has audio output running ('piro' = 1, meaning other people's voices are playing).

- Call apps: bundle prefixes `us.zoom.`, `com.microsoft.teams`, `com.tinyspeck.slackmacgap`,
  `com.hnc.Discord`, `com.apple.FaceTime`, `com.cisco.webex`, `com.apple.WebKit.GPU`, and browser
  helpers (`com.google.Chrome.helper`, `com.brave.Browser.helper`, `company.thebrowser.Browser.helper`,
  `org.mozilla.firefox`)
- Every hit on layer 1 refreshes the timer, so a long unmuted stretch keeps the memory alive
- Trade-off: YouTube in the same browser right after a Meet call stays "busy" until the grace runs out
  or the tab stops playing. Koovi then lights the screen instead of speaking, which is a safe failure

### Diagnosis and logging

- `wait_for_mic` logs who holds the mic: `microphone in use by us.zoom.xos, holding the voice`
- New command `koovi.py mic`: prints the layer used, every recording process, the call memory, and the
  input devices with transport type. You or the CEO can run this during a meeting and paste the output

## Technical Considerations

- **CPU.** One report measured coreaudiod near 53% CPU when an app polled 'piri' on every process about
  16 times per second ([minutes #1127](https://github.com/silverstein/minutes/issues/1127)). Koovi asks
  only right before speaking and while speaking. Slow the mid-sentence watcher in `say_unless_mic()`
  from 0.2 s to 0.5 s and measure coreaudiod during a sentence.
- **No listeners.** Property listeners on 'piri' reportedly never fire on macOS 26 (single report).
  Koovi already polls, so this does not matter.
- **Pure ctypes, no packages.** Same style as `_audio_prop()`; add a CFString reader for 'pbid' and a
  sized-array reader for 'prs#'. `_audio_inputs()` from the first fix already reads arrays.
- **Windows and Linux unchanged.** Windows already checks per app through the consent store. Linux
  stays on ALSA.
- **Safe failure everywhere.** If a read fails, the answer comes from the next layer. If every layer
  fails, the result is "free", which is today's behaviour. Never crash the hook.
- **Ship together** with the uncommitted "mic busy, light the screen instead of chiming" change, so a long
  meeting gets a light, not a sound.

## Edge Cases

| Case | Expected |
|------|----------|
| Zoom with AirPods, unmuted | Busy (layer 1, Zoom `piri = 1`) |
| Zoom muted | Busy (Zoom keeps the mic; if not, layer 3) |
| Meet in Brave or Chrome, muted | Busy (layer 3: helper still playing voices) |
| Music through AirPods, no call | Free |
| Koovi's own voice through AirPods or a USB headset | Free; no self-interruption |
| "Hey Siri" enabled | Free (CoreSpeech ignored) |
| BlackHole or Loopback in use by OBS | Busy only if the app actually records; add it to `mic_ignore_apps` to silence |
| Voibe or macOS dictation running | Busy (intended) |
| Call ended, Zoom holds the device about 30 s ([sigstop](https://dev.to/mohamedelshesheny/how-sigstop-knows-you-are-on-a-call-with-zero-permissions-1kfj)) | Busy briefly, then free; Koovi waits and speaks |
| macOS older than 14.2 | Layer 2 (device check without virtual devices) |

## Acceptance Criteria

- [x] `mic_in_use()` uses process objects when available and returns which app is recording
- [x] CoreSpeech, historicalaudiod, Koovi itself and `mic_ignore_apps` entries never count as busy
- [x] Playing sound into an input+output device does not count as busy (BlackHole playback test)
- [x] Fallback skips virtual and aggregate devices
- [x] A call app seen recording keeps the mic "busy" for `call_grace_seconds` while it still plays audio
- [x] Diary names the app holding the mic; `koovi.py mic` prints the full picture
- [x] New settings in `DEFAULTS` and `config.example.yaml` (`mic_ignore_apps: []`, `call_grace_seconds: 600`); the existing defaults-match test passes
- [x] Unit tests with fake process lists: each row in Edge Cases that does not need hardware
- [ ] Manual checklist on a real Mac (still to do: needs real calls), with `koovi.py mic` output saved per row: Zoom with AirPods (muted
      and unmuted), Meet in Brave (muted and unmuted), FaceTime, music through AirPods, Koovi talking
      through AirPods, Hey Siri on, Voibe dictation
- [ ] coreaudiod CPU during a spoken sentence stays near idle (`top -pid $(pgrep coreaudiod)`)
      Measured 2026-10-20: about 5% of one core while polling twice a second, 0.4% idle. Only during a
      sentence or a wait. Partly met; revisit if anyone notices it

## Success Metrics

- Zero reports of Koovi speaking into a call
- In the diary over one week: "opened mid-sentence" with no recording app named drops to zero
- "still busy after the wait" lines name a real recording app, not an unknown

## Dependencies & Risks

- **macOS version of the process API is not verified.** Mitigated by the layer 2 fallback.
- **Muted-call behaviour of 2026 app versions is not verified.** Mitigated by layer 3 and the manual
  checklist.
- **Browser false "busy" after a call**, for up to `call_grace_seconds`. Falls back to the screen light.
- **Camera as a meeting signal** (CoreMediaIO 'gone') is left out of this fix. Add it only if the manual
  checklist finds a call that layers 1 to 3 miss.

## Files

- `koovi.py`: microphone section (`_audio_prop`, `_audio_inputs`, `mic_in_use`, `wait_for_mic`,
  `say_unless_mic`), `DEFAULTS`, command dispatch (new `mic` command)
- `config.example.yaml`: `mic_ignore_apps`, `call_grace_seconds`
- `tests/test_koovi.py`: `OnACall` class, new fake-process tests
- `CHANGELOG.md`, version bump

## References & Research

- SDK header `CoreAudio.framework/Headers/AudioHardware.h`: 'prs#', 'piri', 'piro', 'pbid', 'ppid', 'pdv#'; 'gone' described as device-wide
- Local measurements on macOS 26.5.1 (scratchpad scripts `mics.py`, `procs.py`): non-default mic missed; BlackHole playback sets 'gone'; 'piri' separates recording from playback; CoreSpeech always `piri = 1`
- Process-object detection: [macnotetaker](https://macnotetaker.com/blog/which-app-is-using-mic-coreaudio-process-objects), [OpenOats #726](https://github.com/yazinsai/OpenOats/issues/726), [sigstop](https://dev.to/mohamedelshesheny/how-sigstop-knows-you-are-on-a-call-with-zero-permissions-1kfj)
- CPU cost of polling: [minutes #1127](https://github.com/silverstein/minutes/issues/1127)
- Bluetooth 'gone' always 0: [Apple forums 741026](https://developer.apple.com/forums/thread/741026)
- Mute behaviour study: [PETS 2022](https://ar5iv.labs.arxiv.org/html/2204.06128)
- AirPods input and output as separate devices: [SuperMegaUltraGroovy](https://supermegaultragroovy.com/2021/01/28/more-on-avaudioengine-airpods/)
