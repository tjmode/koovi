"""Koovi's own checks. Run with:  python3 -m unittest discover -s tests -v
They never touch your real ~/.koovi: every test works in a temporary folder and never makes a sound."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import koovi  # noqa: E402


def transcript(path, user_text="do the thing", tool_uses=0, assistant_text="Done.", ask_tool=None, minutes_ago=2):
    """Write a small Claude Code transcript with one user turn and one assistant turn."""
    t0 = time.time() - minutes_ago * 60
    stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
    blocks = [{"type": "tool_use", "name": "Bash", "id": f"t{i}", "input": {}} for i in range(tool_uses)]
    if ask_tool:
        blocks.append({"type": "tool_use", "name": "AskUserQuestion", "id": "ask", "input": {"questions": [{"question": ask_tool}]}})
    blocks.append({"type": "text", "text": assistant_text})
    lines = [
        {"type": "user", "timestamp": stamp(t0), "message": {"role": "user", "content": [{"type": "text", "text": user_text}]}},
        {"type": "assistant", "timestamp": stamp(t0 + 30), "message": {"role": "assistant", "content": blocks}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return path


class Sandbox(unittest.TestCase):
    """Point every file Koovi touches at a temporary folder, and catch background work instead of running it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="koovi-test-"))
        for name in ("STATE_DIR",):
            setattr(koovi, name, self.tmp)
        koovi.CONFIG_PATH = self.tmp / "config.yaml"
        koovi.STATE_FILE = self.tmp / "state.json"
        koovi.LOG_FILE = self.tmp / "koovi.log"
        koovi.LIGHT_FILE = self.tmp / "light.json"
        koovi.STATE_LOCK = self.tmp / "state.lock"
        koovi.SPEECH_LOCK = self.tmp / "speech.lock"
        self.jobs, self.detached = [], []
        koovi.spawn_worker = lambda job: self.jobs.append(job)
        koovi.spawn_detached = lambda *args: self.detached.append(args)
        koovi.chime = lambda cfg: None
        self.cfg = koovi.load_config()
        self.cfg["focus_check"] = False

    def diary(self):
        return koovi.LOG_FILE.read_text() if koovi.LOG_FILE.exists() else ""

    def stop(self, sid, payload, spoken="Proj", folder="proj", **session):
        now = time.time()
        with koovi.locked_state() as st:
            s = st["sessions"].setdefault(sid, {"folder": folder, "first_seen": now - 600, "last_seen": now})
            s.update(session)
            koovi.decide_stop(self.cfg, st, s, sid, payload, spoken, folder, now)
            return dict(s)


class ConfigReader(Sandbox):
    def test_the_example_matches_the_built_in_defaults(self):
        example = koovi.parse_yaml((ROOT / "config.example.yaml").read_text())
        for key, value in koovi.DEFAULTS.items():
            if key in example and not isinstance(value, (dict, list)):
                self.assertEqual(example[key], value, f"config.example.yaml and DEFAULTS disagree on {key}")
        for key, value in koovi.DEFAULTS["timing"].items():
            self.assertEqual(example["timing"][key], value, f"they disagree on timing.{key}")

    def test_reads_the_example_config(self):
        cfg = koovi.parse_yaml((ROOT / "config.example.yaml").read_text())
        self.assertEqual(cfg["assistant"], "Koovi")
        self.assertEqual(cfg["timing"]["reminders"], 1)
        self.assertEqual(cfg["light"]["colors"]["asking"], "#ff9f0a")
        self.assertEqual(cfg["remind_for"], ["asking", "permission"])
        self.assertIn("{question}", cfg["phrases"]["asking"][0])
        self.assertIsNone(cfg["quiet_hours"]["start"])
        self.assertEqual(cfg["projects"], None)  # only comments under it

    def test_edge_cases(self):
        text = 'a: "x # kept"\nb: [1, "two", {c: d}]\nname with space: { say: "My app", mute: true }\nempty:\nlist:\n  - "{user} hi"\n  - plain\n'
        self.assertEqual(koovi.parse_yaml(text), {
            "a": "x # kept", "b": [1, "two", {"c": "d"}], "name with space": {"say": "My app", "mute": True},
            "empty": None, "list": ["{user} hi", "plain"]})

    def test_bad_file_keeps_defaults_and_says_why(self):
        koovi.CONFIG_PATH.write_text("user: bro\n  broken: [\nvoice Daniel\n")
        cfg = koovi.load_config()
        self.assertEqual(cfg["user"], koovi.DEFAULTS["user"])
        self.assertIn("ERROR reading", self.diary())

    def test_set_and_mute_keep_comments(self):
        koovi.EXAMPLE_CONFIG = ROOT / "config.example.yaml"
        koovi.set_config_value("rate", 190)
        koovi.set_config_value("light.enabled", False)
        koovi.set_config_value("brand_new", "yes please")
        koovi.set_project_mute("my-app", True)
        koovi.set_project_mute("my-app", False)
        koovi.set_project_mute("other-app", True)
        cfg = koovi.parse_yaml(koovi.CONFIG_PATH.read_text())
        self.assertEqual(cfg["rate"], 190)
        self.assertFalse(cfg["light"]["enabled"])
        self.assertEqual(cfg["brand_new"], "yes please")
        self.assertEqual(cfg["projects"]["my-app"], {"mute": False})
        self.assertEqual(cfg["projects"]["other-app"], {"mute": True})
        self.assertIn("# speaking speed", koovi.CONFIG_PATH.read_text())
        self.assertEqual(cfg["light"]["seconds"], 5)  # the rest of the block survived


class Words(Sandbox):
    def test_request_snippet(self):
        self.assertEqual(koovi.request_snippet("ok can you fix the login bug please"), "fix the login bug please")
        self.assertEqual(koovi.request_snippet("ok"), "")
        self.assertEqual(koovi.request_snippet("<task-notification><task-id>x</task-id></task-notification>"), "")
        self.assertEqual(koovi.request_snippet("look at /Users/me/app.py and the <b>bug</b> there"), "look at and the bug there")

    def test_question_snippet(self):
        self.assertEqual(koovi.question_snippet("Two options.\nWhich one do you want?"), "Which one do you want?")
        self.assertEqual(koovi.question_snippet("See `db.py` and https://x.y/z. Use Postgres or SQLite?"), "Use Postgres or SQLite?")
        self.assertEqual(koovi.question_snippet("All done."), "")
        self.assertEqual(koovi.question_from_text("Should I deploy?\n\n1. yes\n2. no"), (False, ""))
        self.assertEqual(koovi.question_from_text("Build finished.\nShould I deploy it now?"), (True, "Should I deploy it now?"))

    def test_phrase_lines_with_and_without_a_question(self):
        st = {}
        self.assertIn("Which one?", koovi.pick_line(self.cfg, "asking", "Proj", st, question="Which one?"))
        self.assertNotIn("{question}", koovi.pick_line(self.cfg, "asking", "Proj", st))
        self.assertNotIn("{question}", koovi.pick_line(self.cfg, "reminder", "Proj", st))

    def test_same_folder_sessions_get_a_label(self):
        now = time.time()
        st = {"sessions": {
            "a": {"folder": "app", "last_seen": now, "first_seen": now - 100, "last_request": "fix the login bug"},
            "b": {"folder": "app", "last_seen": now, "first_seen": now - 50},
            "c": {"folder": "other", "last_seen": now, "first_seen": now}}}
        self.assertEqual(koovi.spoken_with_session(st, st["sessions"]["a"], "a", "app", "App", now), "App, the fix the login bug session")
        self.assertEqual(koovi.spoken_with_session(st, st["sessions"]["b"], "b", "app", "App", now), "App, session 2")
        self.assertEqual(koovi.spoken_with_session(st, st["sessions"]["c"], "c", "other", "Other", now), "Other")


class Transcripts(Sandbox):
    def test_last_turn_is_read(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=3, assistant_text="Done.\nShip it?")
        info = koovi.analyze_transcript(str(path))
        self.assertEqual(info["tool_uses"], 3)
        self.assertTrue(info["is_question"])
        self.assertEqual(info["question"], "Ship it?")
        self.assertEqual(info["last_user_text"], "do the thing")
        self.assertAlmostEqual(info["last_user_ts"], time.time() - 120, delta=5)

    def test_ask_user_question_tool(self):
        path = transcript(self.tmp / "t.jsonl", ask_tool="Installing JDK 21 changes your Mac. How do you want to handle it?")
        info = koovi.analyze_transcript(str(path))
        self.assertTrue(info["is_question"] and info["ask_tool"])
        self.assertIn("How do you want to handle it?", info["question"])

    def test_only_the_tail_of_a_huge_file_is_read(self):
        path = self.tmp / "big.jsonl"
        with open(path, "w") as f:
            for _ in range(20000):
                f.write(json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "old " * 30}]}}) + "\n")
        transcript(self.tmp / "tail.jsonl", tool_uses=1, assistant_text="Finished the tail.")
        with open(path, "a") as f:
            f.write((self.tmp / "tail.jsonl").read_text())
        self.assertGreater(path.stat().st_size, 1_000_000)
        info = koovi.analyze_transcript(str(path))
        self.assertEqual(info["tool_uses"], 1)


class Decisions(Sandbox):
    def test_short_turn_is_quiet(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 3)
        self.assertIn("quiet: short turn", self.diary())
        self.assertEqual(self.jobs, [])

    def test_chat_only_is_quiet(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=0)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.assertIn("quiet: chat only", self.diary())

    def test_real_work_is_announced_once_then_debounced(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(self.jobs[0]["kind"], "done")
        self.assertEqual(self.jobs[0]["reminders"], 0)  # finished work is never nagged
        self.assertIn("quiet: just spoke", self.diary())

    def test_question_is_always_announced_with_the_question(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=0, assistant_text="Quick one.\nRedis or Postgres?")
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 3)
        self.assertEqual(self.jobs[0]["kind"], "asking")
        self.assertEqual(self.jobs[0]["question"], "Redis or Postgres?")
        self.assertEqual(self.jobs[0]["reminders"], 1)
        self.assertIn("Redis or Postgres?", self.jobs[0]["line"])

    def test_last_assistant_message_beats_a_lagging_transcript(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=1, assistant_text="Old turn.\nStill want that?")
        self.stop("s1", {"transcript_path": str(path), "last_assistant_message": "All merged. Nothing else needed."}, last_prompt=time.time() - 40)
        self.assertEqual(self.jobs[0]["kind"], "done")

    def test_background_work_is_announced_unless_you_ask_otherwise(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=1)
        self.stop("s0", {"transcript_path": str(path), "background_tasks": [{"id": "t", "type": "shell", "status": "running"}]}, last_prompt=time.time() - 40)
        self.assertEqual(len(self.jobs), 1, "long-running background work must not silence a finished turn")
        self.jobs.clear()
        self.cfg["wait_for_background_tasks"] = True
        self.stop("s1", {"transcript_path": str(path), "background_tasks": [{"id": "t", "type": "shell", "status": "running"}]}, last_prompt=time.time() - 40)
        self.assertIn("waiting on 1 background task", self.diary())
        self.assertEqual(self.jobs, [])

    def test_wake_up_notice_is_not_your_reply(self):
        self.assertTrue(koovi.is_system_notice("<task-notification>x</task-notification>"))
        self.assertFalse(koovi.is_system_notice("please fix it"))

    def test_quiet_mode_lights_instead_of_talking(self):
        self.cfg["mode"] = "quiet"
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.assertFalse(self.jobs[0]["voice"])
        self.assertTrue(self.jobs[0]["light"])
        self.assertIn("LIGHT done", self.diary())

    def test_muted_project_and_light_render(self):
        now = time.time()
        with koovi.locked_state() as st:
            st["sessions"]["a"] = {"folder": "app", "last_seen": now, "light": {"label": "App", "kind": "done", "at": now, "until": now + 5}}
            st["sessions"]["b"] = {"folder": "web", "last_seen": now, "light": {"label": "Web", "kind": "asking", "at": now, "until": now + 5, "detail": "Redis?"}}
            st["sessions"]["c"] = {"folder": "old", "last_seen": now, "light": {"label": "Old", "kind": "done", "at": now - 60, "until": now - 55}}
            items = koovi.light_render(self.cfg, st)
        self.assertEqual([(i["label"], i["text"]) for i in items], [("Web", "Redis?"), ("App", "done")])


def codex_transcript(path, user_text="add the retry logic", tools=2, assistant_text="Done.", minutes_ago=2):
    """A Codex rollout file: one user message, some function calls, one assistant message."""
    t0 = time.time() - minutes_ago * 60
    stamp = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
    rows = [
        {"timestamp": stamp(t0 - 5), "type": "session_meta", "payload": {"id": "x", "cwd": "/tmp"}},
        {"timestamp": stamp(t0 - 1), "type": "response_item",
         "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "system rules"}]}},
        {"timestamp": stamp(t0), "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": user_text}]}},
    ]
    for i in range(tools):
        rows.append({"timestamp": stamp(t0 + 10 + i), "type": "response_item",
                     "payload": {"type": "function_call", "name": "shell", "arguments": "{}"}})
        rows.append({"timestamp": stamp(t0 + 11 + i), "type": "response_item",
                     "payload": {"type": "function_call_output", "output": "ok"}})
    rows.append({"timestamp": stamp(t0 + 30), "type": "response_item",
                 "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": assistant_text}]}})
    rows.append({"timestamp": stamp(t0 + 31), "type": "event_msg", "payload": {"type": "token_count", "count": 12}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


class OtherTools(Sandbox):
    """Codex and Cursor send different shapes. One reader, one set of rules."""

    def test_reads_a_codex_transcript(self):
        path = codex_transcript(self.tmp / "rollout.jsonl", tools=3, assistant_text="All set.\nShall I push it?")
        info = koovi.analyze_transcript(str(path))
        self.assertTrue(info["readable"])
        self.assertEqual(info["tool_uses"], 3)
        self.assertEqual(info["last_user_text"], "add the retry logic")
        self.assertTrue(info["is_question"])
        self.assertEqual(info["question"], "Shall I push it?")
        self.assertAlmostEqual(info["last_user_ts"], time.time() - 120, delta=5)

    def test_codex_work_is_announced(self):
        path = codex_transcript(self.tmp / "rollout.jsonl", tools=2)
        self.stop("c1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.assertEqual(self.jobs[0]["kind"], "done")

    def test_a_transcript_we_cannot_read_is_not_mistaken_for_idle_chat(self):
        blank = self.tmp / "cursor.jsonl"
        blank.write_text(json.dumps({"type": "something-else", "value": 1}) + "\n")
        for i, payload in enumerate(({"transcript_path": str(blank)}, {"transcript_path": None})):
            self.jobs.clear()
            self.stop(f"unreadable-{i}", payload, folder=f"folder-{i}", last_prompt=time.time() - 40)
            self.assertEqual(len(self.jobs), 1, "an unreadable transcript must not silence a real turn")
            self.assertIn(self.jobs[0]["kind"], ("done", "also_done"))

    def test_payload_fields_each_tool_names_differently(self):
        import io
        for raw, sid, folder in (
            ({"session_id": "a", "cwd": "/x/app"}, "a", "/x/app"),
            ({"conversation_id": "b", "workspace_roots": ["/x/web", "/x/other"]}, "b", "/x/web"),
        ):
            stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(raw))
            try:
                got = koovi.hook_payload()
            finally:
                sys.stdin = stdin
            self.assertEqual((got["session_id"], got["cwd"]), (sid, folder))

    def test_permission_is_spoken_even_on_that_window(self):
        now = time.time()
        with koovi.locked_state() as st:
            s = st["sessions"].setdefault("p1", {"folder": "app", "first_seen": now, "last_seen": now})
            koovi.decide_permission(self.cfg, st, s, "p1", "permission", "App", "app", now, tool="Bash")
        self.assertEqual(self.jobs[0]["kind"], "permission")
        self.assertEqual(self.jobs[0]["reminders"], 1)


class Platforms(Sandbox):
    """Windows and Linux take different commands for the same jobs. Not yet tried on a real machine."""

    def use(self, name, has=()):
        self.addCleanup(setattr, koovi, "OS", koovi.OS)
        koovi.OS = name
        real_which = koovi.shutil.which
        koovi.shutil.which = lambda program: f"/usr/bin/{program}" if program in has else None
        self.addCleanup(setattr, koovi.shutil, "which", real_which)

    def test_the_voice_on_each_machine(self):
        self.cfg.update(voice="Zira", rate=190)
        self.use("mac")
        self.addCleanup(setattr, koovi, "voice_installed", koovi.voice_installed)
        koovi.voice_installed = lambda name: True
        self.assertEqual(koovi.speech_command(self.cfg, "hi")[0], ["say", "-v", "Zira", "-r", "190", "hi"])
        koovi.voice_installed = lambda name: False  # a name this Mac does not have: never silence
        self.assertEqual(koovi.speech_command(self.cfg, "hi")[0], ["say", "-r", "190", "hi"])
        self.assertIn("speaking with the system voice", self.diary())
        koovi.voice_installed = lambda name: True
        self.use("windows")
        command, env = koovi.speech_command(self.cfg, "hi")
        self.assertEqual(command[0], "powershell")
        self.assertEqual((env["KOOVI_TEXT"], env["KOOVI_VOICE"], env["KOOVI_RATE"]), ("hi", "Zira", "-1"))
        self.use("linux", has=("spd-say",))
        self.assertEqual(koovi.speech_command(self.cfg, "hi")[0], ["spd-say", "-w", "-r", "9", "hi"])
        self.use("linux", has=("espeak-ng",))
        self.assertEqual(koovi.speech_command(self.cfg, "hi")[0], ["espeak-ng", "-s", "190", "hi"])
        self.use("linux")
        self.assertIsNone(koovi.speech_command(self.cfg, "hi")[0])

    def test_the_chime_on_each_machine(self):
        self.cfg["chime"] = "/nowhere/glass.aiff"
        self.use("mac")
        self.assertIsNone(koovi.chime_command(self.cfg))
        self.use("windows")
        self.assertIn("beep", koovi.chime_command(self.cfg)[-1])
        self.use("linux")
        self.assertEqual(koovi.chime_command(self.cfg)[0], "sh")  # the terminal bell, as a last resort

    def test_music_and_browsers_are_left_alone_off_mac(self):
        for name in ("windows", "linux"):
            self.use(name)
            self.assertIsNone(koovi.duck_music(self.cfg))
            self.assertEqual(koovi.duck_browsers(self.cfg), [])
            self.assertEqual(list(koovi._running_browsers()), [])

    def test_auto_mode_talks_when_headphones_cannot_be_checked(self):
        self.use("windows")
        self.cfg["mode"] = "auto"
        allowed, why = koovi.voice_allowed(self.cfg)
        self.assertTrue(allowed)
        self.assertIn("cannot tell", why)

    def test_the_screen_light_per_machine(self):
        self.use("windows")
        command = next(koovi.light_commands(), None)
        self.assertIsNotNone(command, "the Windows screen light script should ship with Koovi")
        self.assertEqual(command[-2:], [str(koovi.LIGHT_PS1), str(koovi.LIGHT_FILE)])
        self.use("linux")
        self.assertEqual(list(koovi.light_commands()), [])
        self.assertIn("needs macOS or Windows", self.diary())


class Packaging(unittest.TestCase):
    def test_versions_agree(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertEqual(manifest["version"], koovi.KOOVI_VERSION)
        self.assertEqual(market["plugins"][0]["version"], koovi.KOOVI_VERSION)
        self.assertIn(f"## {koovi.KOOVI_VERSION}", changelog)

    def test_the_readme_badge_shows_the_current_version(self):
        self.assertIn(f"version-{koovi.KOOVI_VERSION}-", (ROOT / "README.md").read_text())

    def test_the_marketplace_entry_stays_conservative(self):
        entry = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]
        allowed = {"name", "source", "version", "description", "author", "homepage",
                   "repository", "license", "keywords", "category"}
        self.assertEqual(set(entry) - allowed, set(),
                         "older Claude Code versions reject unknown keys in a marketplace entry")

    def test_the_manifest_does_not_name_the_hooks_file(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertTrue((ROOT / "hooks" / "hooks.json").exists())
        self.assertNotIn("hooks", manifest,
                         "hooks/hooks.json loads on its own; naming it again makes the plugin fail to load")

    def test_hooks_cover_every_event_koovi_handles(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"UserPromptSubmit", "Stop", "Notification", "SubagentStop", "SessionEnd"})
        for groups in hooks.values():
            for g in groups:
                for h in g["hooks"]:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", h["command"])
                    self.assertIn("koovi.sh", h["command"])

    def test_the_windows_light_script_ships(self):
        self.assertTrue((ROOT / "light" / "KooviLight.ps1").exists())
        self.assertIn("KooviLight", (ROOT / "light" / "KooviLight.ps1").read_text())

    def test_no_personal_settings_in_the_repo(self):
        self.assertFalse((ROOT / "config.yaml").exists(), "config.yaml must not be in the repo; use config.example.yaml")
        self.assertIn("config.yaml", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
