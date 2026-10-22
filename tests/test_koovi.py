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
        koovi.CALL_FILE = self.tmp / "call.json"
        koovi.STATE_LOCK = self.tmp / "state.lock"
        koovi.CONFIG_LOCK = self.tmp / "config.lock"
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

    def test_a_brand_new_install_can_announce(self):
        """The whole path a first-time user takes, on the settings file we ship."""
        koovi.EXAMPLE_CONFIG = ROOT / "config.example.yaml"
        cfg = koovi.load_config()                       # writes the settings file, as a new install does
        self.assertEqual(cfg["projects"], {})           # a heading with only comments under it is not None
        self.assertEqual(koovi.project_settings(cfg, "some-folder"), {"say": "some folder", "mute": False})
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        now = time.time()
        with koovi.locked_state() as st:
            s = st["sessions"].setdefault("new", {"folder": "some-folder", "first_seen": now - 600,
                                                  "last_seen": now, "last_prompt": now - 40})
            koovi.decide_stop(cfg, st, s, "new", {"transcript_path": str(path)}, "Some folder", "some-folder", now)
        self.assertEqual(len(self.jobs), 1, "a fresh install must be able to speak")
        self.assertNotIn("ERROR", self.diary())

    def test_an_empty_heading_never_replaces_a_default(self):
        koovi.CONFIG_PATH.write_text("projects:\nphrases:\ntiming:\nlight:\nuser: chief\n")
        cfg = koovi.load_config()
        self.assertEqual(cfg["user"], "chief")
        self.assertEqual(cfg["timing"]["min_task_seconds"], koovi.DEFAULTS["timing"]["min_task_seconds"])
        self.assertTrue(cfg["phrases"]["done"] and cfg["light"]["enabled"])
        self.assertEqual(koovi.project_settings(cfg, "x"), {"say": "x", "mute": False})

    def test_reads_the_example_config(self):
        cfg = koovi.parse_yaml((ROOT / "config.example.yaml").read_text())
        self.assertEqual(cfg["assistant"], "Koovi")
        self.assertEqual(cfg["timing"]["reminders"], 1)
        self.assertEqual(cfg["light"]["colors"]["asking"], "#ff9f0a")
        self.assertEqual(cfg["remind_for"], ["asking", "permission"])
        self.assertIn("{question}", cfg["phrases"]["asking"][0])
        self.assertIsNone(cfg["quiet_hours"]["start"])
        self.assertIsNone(cfg["projects"])  # only comments under it; load_config turns this into {}

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
            "a": {"folder": "app", "last_seen": now, "first_seen": now - 100, "rename": "Login work"},
            "b": {"folder": "app", "last_seen": now, "first_seen": now - 50},
            "c": {"folder": "other", "last_seen": now, "first_seen": now}}}
        self.assertEqual(koovi.spoken_with_session(st, st["sessions"]["a"], "a", "app", "App", now), "App, Login work")
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

    def test_research_agents_hold_the_done_until_they_finish(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        agents = [{"id": "a", "type": "subagent", "status": "running", "agent_type": "general-purpose"},
                  {"id": "b", "type": "shell", "status": "running"}]
        self.stop("s1", {"transcript_path": str(path), "background_tasks": agents}, last_prompt=time.time() - 40)
        self.assertEqual(self.jobs, [], "a turn that is waiting on research is not done")
        self.assertIn("1 agent(s) still working", self.diary())
        # an agent wakes the session, and Claude goes straight back to waiting on the next one
        self.stop("s1", {"transcript_path": str(path), "background_tasks": agents[:1]}, last_wake=time.time() - 3)
        self.assertEqual(self.jobs, [])
        # the last agent is back; the wrap-up is short, but it is the end of the whole job
        self.stop("s1", {"transcript_path": str(path), "background_tasks": agents[1:]}, last_wake=time.time() - 3)
        self.assertEqual(len(self.jobs), 1)
        self.assertEqual(self.jobs[0]["kind"], "done")
        self.assertIn("after_agents=True", self.diary())

    def test_a_question_is_not_held_by_running_agents(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=1, assistant_text="Agents are out.\nShip it now or wait?")
        agents = [{"id": "a", "type": "workflow", "status": "running"}]
        self.stop("s1", {"transcript_path": str(path), "background_tasks": agents}, last_prompt=time.time() - 40)
        self.assertEqual(self.jobs[0]["kind"], "asking")

    def test_your_new_prompt_clears_a_stale_agent_wait(self):
        path = transcript(self.tmp / "t.jsonl", tool_uses=1)
        self.stop("s1", {"transcript_path": str(path), "background_tasks": [{"id": "a", "type": "subagent", "status": "running"}]},
                  last_prompt=time.time() - 40)
        with koovi.locked_state() as st:
            self.assertTrue(st["sessions"]["s1"].get("awaiting_agents"))
        self.addCleanup(setattr, koovi, "hook_payload", koovi.hook_payload)
        koovi.hook_payload = lambda: {"session_id": "s1", "cwd": str(self.tmp / "proj"), "prompt": "now do the next bit"}
        koovi.cmd_hook("prompt")
        with koovi.locked_state() as st:
            self.assertNotIn("awaiting_agents", st["sessions"]["s1"])
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 2)
        self.assertEqual(self.jobs, [], "a short reply to your new ask stays quiet as before")

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


class TheLadder(Sandbox):
    """One word, one reminder, then gone. On a window you are already reading, the first word is held."""

    def setUp(self):
        super().setUp()
        self.was_focused, self.was_intimate = koovi.is_focused, koovi.intimate
        self.said = []
        koovi.intimate = lambda cfg, job, line, kind: self.said.append((kind, line))

    def tearDown(self):
        koovi.is_focused, koovi.intimate = self.was_focused, self.was_intimate

    def looking_at_it(self, yes):
        koovi.is_focused = lambda folder: (yes, "Terminal", folder)

    def finish_a_turn(self, **payload):
        payload.setdefault("tool_uses", 2)
        path = transcript(self.tmp / "t.jsonl", **payload)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        return self.jobs[0]

    def test_a_window_you_are_reading_hears_nothing_yet(self):
        self.cfg["focus_check"] = True
        self.looking_at_it(True)
        job = self.finish_a_turn()
        self.assertTrue(job["held"])
        self.assertEqual(job["reminders"], 1)  # a finish is never nagged, but held it has said nothing at all
        self.assertIn("HOLD done", self.diary())

    def test_a_window_you_are_not_on_hears_it_at_once(self):
        self.cfg["focus_check"] = True
        self.looking_at_it(False)
        job = self.finish_a_turn()
        self.assertFalse(job["held"])
        self.assertEqual(job["reminders"], 0)

    def test_holding_says_nothing_at_all_when_reminders_are_off(self):
        self.cfg["focus_check"] = True
        self.cfg["timing"]["reminders"] = 0
        self.looking_at_it(True)
        path = transcript(self.tmp / "t.jsonl", tool_uses=2)
        self.stop("s1", {"transcript_path": str(path)}, last_prompt=time.time() - 40)
        self.assertEqual(self.jobs, [])
        self.assertIn("quiet: you are on that window", self.diary())

    def test_a_held_line_is_the_one_you_finally_hear(self):
        koovi.CONFIG_PATH.write_text("focus_check: true\ntiming:\n  reminder_after_seconds: 0\n")
        now = time.time()
        with koovi.locked_state() as st:
            st["sessions"]["s1"] = {"folder": "proj", "first_seen": now - 600, "last_seen": now,
                                    "last_prompt": now - 40}
        job = {"session": "s1", "project": "Proj", "folder": "proj", "kind": "done", "line": "Proj is done.",
               "held": True, "spoken_at": now, "reminders": 1, "voice": True, "light": False, "question": ""}
        koovi.cmd_announce(json.dumps(job))
        self.assertEqual(self.said, [("done", "Proj is done.")])  # said once, in its own words, then gone

    def test_a_held_line_is_dropped_the_moment_you_type(self):
        koovi.CONFIG_PATH.write_text("focus_check: true\ntiming:\n  reminder_after_seconds: 0\n")
        now = time.time()
        with koovi.locked_state() as st:
            st["sessions"]["s1"] = {"folder": "proj", "first_seen": now - 600, "last_seen": now,
                                    "last_prompt": now + 1}  # you replied after it was held
        job = {"session": "s1", "project": "Proj", "folder": "proj", "kind": "done", "line": "Proj is done.",
               "held": True, "spoken_at": now, "reminders": 1, "voice": True, "light": False, "question": ""}
        koovi.cmd_announce(json.dumps(job))
        self.assertEqual(self.said, [])
        self.assertIn("you already replied", self.diary())

    def test_a_permission_speaks_even_on_that_window(self):
        self.cfg["focus_check"] = True
        self.looking_at_it(True)
        now = time.time()
        with koovi.locked_state() as st:
            s = st["sessions"].setdefault("s1", {"folder": "proj", "first_seen": now - 600, "last_seen": now})
            koovi.decide_permission(self.cfg, st, s, "s1", "notification", "Proj", "proj", now)
        self.assertFalse(self.jobs[0]["held"])  # you answer these by clicking; nothing tells us that you did

    def test_the_question_is_cut_down_for_speech(self):
        self.cfg["focus_check"] = False
        long = "Should we keep the old migration path around for another release or drop it right now?"
        job = self.finish_a_turn(tool_uses=0, assistant_text="Two ways.\n" + long)
        self.assertLessEqual(len(job["question"].split()), self.cfg["question_words"])
        self.assertIn(job["question"], job["line"])


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


class OnACall(Sandbox):
    """The microphone is busy, so you are dictating or in a meeting: catch the eye, never the ear."""

    def busy_mic(self):
        self.addCleanup(setattr, koovi, "mic_in_use", koovi.mic_in_use)
        koovi.mic_in_use = lambda cfg=None: "us.zoom.xos"
        self.cfg["wait_for_mic"] = True
        self.cfg["mic_wait_max_seconds"] = 0  # give up on the voice at once instead of waiting two minutes
        self.chimed = []
        koovi.chime = lambda cfg: self.chimed.append(True)

    def job(self, light=False):
        return {"session": "s1", "project": "Voibe", "folder": "voibe", "kind": "done",
                "line": "Voibe is done.", "held": False, "spoken_at": time.time(),
                "reminders": 0, "voice": True, "light": light, "question": ""}

    def test_the_voice_gives_up_while_the_mic_is_busy(self):
        self.busy_mic()
        self.assertFalse(koovi.speak(self.cfg, "Voibe is done."))

    def test_a_busy_mic_lights_the_screen_instead_of_making_a_sound(self):
        self.busy_mic()
        koovi.intimate(self.cfg, self.job(), "Voibe is done.", "done")
        self.assertEqual(self.chimed, [])  # no chime in the middle of your meeting
        self.assertIn("Voibe", koovi.LIGHT_FILE.read_text())
        self.assertIn("lit the screen instead of speaking", self.diary())

    def test_the_chime_is_the_last_resort_when_the_light_is_off(self):
        self.busy_mic()
        self.cfg["light"] = {"enabled": False}
        koovi.intimate(self.cfg, self.job(), "Voibe is done.", "done")
        self.assertEqual(self.chimed, [True])

    def test_a_job_already_lit_is_not_lit_twice(self):
        self.busy_mic()
        koovi.intimate(self.cfg, self.job(light=True), "Voibe is done.", "done")
        self.assertEqual(self.chimed, [])
        self.assertEqual(self.diary().count("lit the screen instead"), 0)


class WhoHasTheMic(Sandbox):
    """On a Mac: ask which app is recording, not which device is running."""

    def setUp(self):
        super().setUp()
        for name in ("OS", "_audio_processes", "_audio_inputs", "_audio_prop"):
            self.addCleanup(setattr, koovi, name, getattr(koovi, name))
        koovi.OS = koovi.MAC
        self.procs = []
        koovi._audio_processes = lambda: self.procs

    def app(self, app, pid, input=False, output=False):
        self.procs.append({"pid": pid, "app": app, "input": input, "output": output})

    def test_a_call_on_any_microphone_is_busy(self):
        self.app("us.zoom.xos", 500, input=True, output=True)  # recording from the headset, whatever the default is
        self.assertEqual(koovi.mic_in_use(self.cfg), "us.zoom.xos")

    def test_playing_sound_is_not_recording(self):
        self.app("com.apple.Music", 501, output=True)  # music through AirPods
        self.app("say", 502, output=True)  # Koovi's own voice
        self.assertEqual(koovi.mic_in_use(self.cfg), "")

    def test_hey_siri_and_ignored_apps_never_count(self):
        self.app("com.apple.CoreSpeech", 886, input=True)
        self.app("historicalaudiod", 887, input=True)
        self.app("ai.krisp.krispMac", 888, input=True)
        self.cfg["mic_ignore_apps"] = ["ai.krisp.krispMac"]
        self.assertEqual(koovi.mic_in_use(self.cfg), "")

    def test_dictation_counts(self):
        self.app("com.voibe.app", 600, input=True)
        self.assertEqual(koovi.mic_in_use(self.cfg), "com.voibe.app")

    def test_a_muted_web_call_still_counts_while_people_are_talking(self):
        self.app("com.brave.Browser.helper", 700, input=True, output=True)
        self.assertTrue(koovi.mic_in_use(self.cfg))
        self.procs[0]["input"] = False  # you muted Meet; the browser lets go of the mic but still plays the call
        self.assertIn("com.brave.Browser.helper", koovi.mic_in_use(self.cfg))
        self.procs[0]["output"] = False  # call over, nothing playing
        self.assertEqual(koovi.mic_in_use(self.cfg), "")

    def test_the_call_memory_runs_out(self):
        self.app("us.zoom.xos", 500, output=True)
        koovi.remember_call({"app": "us.zoom.xos", "pid": 500}, time.time() - self.cfg["call_grace_seconds"] - 1)
        self.assertEqual(koovi.mic_in_use(self.cfg), "")

    def test_a_non_call_app_recording_is_not_remembered(self):
        self.app("com.voibe.app", 600, input=True, output=True)
        koovi.mic_in_use(self.cfg)
        self.procs[0]["input"] = False
        self.assertEqual(koovi.mic_in_use(self.cfg), "", "dictation that stopped is over; only calls are remembered")

    def test_older_macs_check_real_devices_only(self):
        koovi._audio_processes = lambda: None  # no per-app answer before macOS 14.2
        koovi._audio_inputs = lambda: [73, 97, 120]  # BlackHole (virtual), built-in mic (default), headset
        tran = {73: koovi._fourcc("virt"), 97: koovi._fourcc("bltn"), 120: koovi._fourcc("usb ")}
        running = {73: 1, 97: 0, 120: 0}
        koovi._audio_prop = lambda obj, sel, scope: tran.get(obj) if sel == "tran" else running.get(obj)
        self.assertEqual(koovi.mic_in_use(self.cfg), "", "a virtual device running all day is not a person")
        running[120] = 1  # the headset mic, not the default one
        self.assertEqual(koovi.mic_in_use(self.cfg), "a microphone")


class OnAndOff(Sandbox):
    """enabled: false means silence everywhere, at once, while Koovi keeps track of your sessions."""

    def turn(self, on):
        self.assertEqual(koovi.cmd_set("enabled", "true" if on else "false"), 0)

    def hook(self, event, **payload):
        self.addCleanup(setattr, koovi, "hook_payload", koovi.hook_payload)
        payload.update({"session_id": "s1", "cwd": str(self.tmp / "proj")})
        koovi.hook_payload = lambda: payload
        koovi.cmd_hook(event)

    def test_off_says_nothing_but_still_keeps_track(self):
        self.turn(False)
        path = transcript(self.tmp / "t.jsonl", tool_uses=3)
        self.hook("prompt", prompt="build it")
        self.hook("stop", transcript_path=str(path))
        self.assertEqual(self.jobs, [])
        self.assertIn("quiet: Koovi is off", self.diary())
        with koovi.locked_state() as st:
            self.assertTrue(st["sessions"]["s1"].get("last_prompt"), "your prompt is still recorded")

    def test_a_waiting_reminder_stays_quiet_once_you_turn_it_off(self):
        said = []
        self.addCleanup(setattr, koovi, "intimate", koovi.intimate)
        koovi.intimate = lambda cfg, job, line, kind: said.append(line)
        koovi.set_config_value("timing.reminder_after_seconds", 0)
        self.turn(False)
        now = time.time()
        with koovi.locked_state() as st:
            st["sessions"]["s1"] = {"folder": "proj", "first_seen": now - 600, "last_seen": now, "last_prompt": now - 40}
        job = {"session": "s1", "project": "Proj", "folder": "proj", "kind": "asking", "line": "Proj asks.",
               "held": True, "spoken_at": now, "reminders": 1, "voice": True, "light": False, "question": ""}
        koovi.cmd_announce(json.dumps(job))
        self.assertEqual(said, [])
        self.assertIn("skipped: Koovi is off", self.diary())

    def test_a_line_that_waited_for_the_mic_checks_the_switch_again(self):
        saved = (koovi.wait_for_mic, koovi.say_unless_mic, koovi.duck_music)
        self.addCleanup(lambda: (setattr(koovi, "wait_for_mic", saved[0]), setattr(koovi, "say_unless_mic", saved[1]),
                                 setattr(koovi, "duck_music", saved[2])))
        said = []

        def call_ends_and_you_had_turned_it_off(cfg):
            koovi.set_config_value("enabled", False)
            return True
        koovi.wait_for_mic = call_ends_and_you_had_turned_it_off
        koovi.say_unless_mic = lambda cfg, text: said.append(text)
        koovi.duck_music = lambda cfg: said.append("ducked")
        self.assertTrue(koovi.speak(self.cfg, "Proj is done."), "no light to make up for it either")
        self.assertEqual(said, [])

    def test_nothing_starts_once_it_is_off(self):
        spoken = []
        self.addCleanup(setattr, koovi, "speak", koovi.speak)
        koovi.speak = lambda cfg, text, obey_off=True: spoken.append(text)
        self.turn(False)
        koovi.intimate(self.cfg, {"project": "Proj", "light": True, "voice": True}, "Proj is done.", "done")
        self.assertEqual(spoken, [])
        self.assertFalse(koovi.LIGHT_FILE.exists() and json.loads(koovi.LIGHT_FILE.read_text())["items"])

    def test_the_test_line_still_plays_and_says_it_is_off(self):
        heard = []
        self.addCleanup(setattr, koovi, "speak", koovi.speak)
        koovi.speak = lambda cfg, text, obey_off=True: heard.append(obey_off)
        self.turn(False)
        koovi.cmd_test("done", "Proj")
        self.assertEqual(heard, [False])

    def test_turning_off_puts_out_a_light_that_is_showing(self):
        now = time.time()
        with koovi.locked_state() as st:
            s = st["sessions"].setdefault("s1", {"folder": "proj", "last_seen": now})
            s["light"] = {"label": "Proj", "kind": "done", "at": now, "until": now + 60}
            koovi.light_render(self.cfg, st)
        self.assertTrue(json.loads(koovi.LIGHT_FILE.read_text())["items"])
        self.turn(False)
        self.assertEqual(json.loads(koovi.LIGHT_FILE.read_text())["items"], [])

    def test_an_old_settings_file_without_the_switch_counts_as_on_and_takes_it(self):
        koovi.CONFIG_PATH.write_text("user: boss\n")
        self.assertTrue(koovi.load_config()["enabled"])
        self.turn(False)
        self.assertFalse(koovi.load_config()["enabled"])
        self.assertEqual(koovi.load_config()["user"], "boss")


class SettingsScreen(Sandbox):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, koovi, "mic_in_use", koovi.mic_in_use)
        koovi.mic_in_use = lambda cfg=None: "us.zoom.xos"

    def test_set_refuses_what_is_not_a_setting_or_not_the_right_kind(self):
        before = koovi.CONFIG_PATH.read_text()
        for key, value in (("enabeld", "false"), ("mode", "loud"), ("wait_for_mic", "sometimes"),
                           ("rate", "fast"), ("quiet_hours.start", "late"), ("phrases", "x"), ("projects.app", "x")):
            self.assertEqual(koovi.cmd_set(key, value), 1, f"{key} {value} should be refused")
        self.assertEqual(koovi.CONFIG_PATH.read_text(), before)

    def test_set_takes_what_it_should(self):
        for key, value in (("mode", "quiet"), ("wait_for_agents", "false"), ("rate", "190"),
                           ("quiet_hours.start", "23:00"), ("quiet_hours.end", "08:00"), ("light.corner", "bottom-left")):
            self.assertEqual(koovi.cmd_set(key, value), 0, f"{key} {value}")
        cfg = koovi.load_config()
        self.assertEqual((cfg["mode"], cfg["wait_for_agents"], cfg["rate"]), ("quiet", False, 190))
        self.assertTrue(koovi.in_quiet_hours(cfg) in (True, False))
        self.assertEqual(koovi.cmd_set("quiet_hours.start", "off"), 0)
        self.assertIsNone(koovi.load_config()["quiet_hours"]["start"])

    def test_a_file_that_does_not_read_is_never_written_over(self):
        koovi.CONFIG_PATH.write_text("user: boss\nmode voice\n")
        self.assertEqual(koovi.cmd_set("mode", "quiet"), 1)
        self.assertEqual(koovi.cmd_mute(True, "proj"), 1)
        self.assertEqual(koovi.CONFIG_PATH.read_text(), "user: boss\nmode voice\n")
        snap = koovi.settings_snapshot()
        self.assertIn("cannot read line", snap["error"])
        self.assertEqual(koovi.cmd_settings(), 1)

    def test_two_changes_at_the_same_moment_both_land(self):
        import threading
        changes = [("rate", 190), ("user", "tony"), ("question_words", 6)] * 30
        start = threading.Barrier(len(changes))

        def write(key, value):
            start.wait()  # all at the same moment
            koovi.set_config_value(key, value)
        writers = [threading.Thread(target=write, args=change) for change in changes]
        for w in writers:
            w.start()
        for w in writers:
            w.join()
        cfg = koovi.load_config()
        self.assertEqual((cfg["rate"], cfg["user"], cfg["question_words"]), (190, "tony", 6))

    def test_the_snapshot_holds_the_main_switches(self):
        now = time.time()
        with koovi.locked_state() as st:
            st["sessions"]["a"] = {"folder": "payments", "last_seen": now}
            st["sessions"]["b"] = {"folder": "checkout", "last_seen": now - 60}
        koovi.set_project_mute("checkout", True)
        snap = koovi.settings_snapshot()
        self.assertEqual((snap["enabled"], snap["mode"], snap["wait_for_mic"], snap["wait_for_agents"]),
                         (True, "voice", True, True))
        self.assertEqual(snap["mic"], "us.zoom.xos")
        self.assertEqual(snap["muted"], ["checkout"])
        self.assertEqual(snap["recent_projects"], ["payments", "checkout"])
        self.assertEqual(snap["version"], koovi.KOOVI_VERSION)
        self.assertEqual(snap["error"], "")


class Packaging(unittest.TestCase):
    def test_versions_agree(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
        changelog = (ROOT / "CHANGELOG.md").read_text()
        self.assertEqual(manifest["version"], koovi.KOOVI_VERSION)
        self.assertEqual(market["plugins"][0]["version"], koovi.KOOVI_VERSION)
        self.assertIn(f"## {koovi.KOOVI_VERSION}", changelog)

    def test_the_readme_links_point_somewhere_real(self):
        import re
        readme = (ROOT / "README.md").read_text()
        for target in re.findall(r"\]\((?!http)([^)#]+)\)", readme):
            self.assertTrue((ROOT / target).exists(), f"README links to {target}, which is not in the repo")
        self.assertIn("discord.gg/", readme)

    def test_the_readme_badge_shows_the_current_version(self):
        self.assertIn(f"version-{koovi.KOOVI_VERSION}-", (ROOT / "README.md").read_text())

    def test_the_marketplace_entry_stays_conservative(self):
        entry = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]
        allowed = {"name", "source", "version", "description", "author", "homepage",
                   "repository", "license", "keywords", "category"}
        self.assertEqual(set(entry) - allowed, set(),
                         "older Claude Code versions reject unknown keys in a marketplace entry")

    def test_every_command_file_has_a_readable_header(self):
        """A second colon in a description makes the header invalid, and Claude Code then skips
        the command silently. That shipped once; it does not ship again."""
        files = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            _, header, body = path.read_text().split("---", 2)
            fields = {}
            for line in header.strip().splitlines():
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
                if not (value.startswith('"') or value.startswith("'")):
                    self.assertNotIn(": ", value, f"{path.name} header line needs quoting: {line}")
            self.assertEqual(fields.get("name"), path.parent.name, f"{path} name must match its folder")
            self.assertTrue(fields.get("description"), f"{path} needs a description")
            self.assertIn("${CLAUDE_PLUGIN_ROOT}/koovi.sh", body)

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
