#!/usr/bin/env python3
"""Controls for a project's own task-id convention in artifacts.py (stdlib only).

A project may name its tasks its own way (MiOS uses task_<26-char ULID>). It declares the shape once,
$DEVLOOP_TASK_ID_RE or "task_id_pattern" in .devloop/config.json, and that shape is ADDED to the
built-in one, never put in its place.

Cases (each in a throwaway git repo; this checkout is never touched):
  (a) no declaration: a task_<ULID> id is rejected (the default is unchanged)
  (b) $DEVLOOP_TASK_ID_RE: validate accepts it, and still rejects an id of neither shape
  (c) .devloop/config.json: the same beside the file's other keys, and the env var wins over the file
  (d) the built-in shapes (T-001) stay valid with a project pattern declared
  (e) a pattern that would accept any id ('.*', '.+', '[^\\n]*') is refused, naming the probe it matched
  (f) an uncompilable pattern is refused with the regex error
  (g) export-openai carries the project shape in the id pattern

Negative control: make validate() ignore its extra pattern and (b), (c) and (d) fail; drop the
vacuity probes and (e) fails.

Run: python3 tests/test_task_id_pattern.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ART = REPO / "skills" / "dev-loop" / "scripts" / "artifacts.py"
ULID_ID = "task_0000000000WYZ1N7FZ5VRQDBET"
PATTERN = r"task_[0-9A-Z]{26}"


def rec(i, **kw):
    return {"id": i, "type": "task", "title": f"title {i}", "status": "open", "depends_on": [], **kw}


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="task-id-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("DEVLOOP_TASKS_FILE", "DEVLOOP_TASK_ID_RE")}

    def tasks(self, *records):
        (self.root / "tasks.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records), "utf-8")

    def config(self, pattern):
        p = self.root / ".devloop" / "config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        # beside unrelated keys, the way a project's existing dev-loop config holds it
        p.write_text(json.dumps({"version": "2.0.0", "roles": ["Builder"], "task_id_pattern": pattern}), "utf-8")

    def art(self, *args, env_extra=None):
        env = dict(self.env, **(env_extra or {}))
        return subprocess.run([sys.executable, str(ART), "tasks", *args, "--root", str(self.root)],
                              capture_output=True, text=True, env=env, cwd=self.root)


class ProjectPattern(Base):
    def test_a_default_rejects_ulid_ids(self):
        self.tasks(rec(ULID_ID))
        cp = self.art("validate")
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("id must look like", cp.stdout + cp.stderr)

    def test_b_env_pattern_accepts_and_still_rejects(self):
        self.tasks(rec(ULID_ID))
        cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": PATTERN})
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("tasks.jsonl ok: 1 tasks", cp.stdout)
        self.tasks(rec(ULID_ID), rec("task_short"))
        cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": PATTERN})
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("'task_short': id must look like", cp.stdout + cp.stderr)
        self.assertIn(PATTERN, cp.stdout + cp.stderr)

    def test_c_config_file_and_env_precedence(self):
        self.tasks(rec(ULID_ID))
        self.config(PATTERN)
        cp = self.art("validate")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": r"job-[0-9]+"})
        self.assertNotEqual(cp.returncode, 0, "the env var must win over the file")
        self.assertIn("job-[0-9]+", cp.stdout + cp.stderr)

    def test_d_builtin_shapes_still_valid(self):
        self.tasks(rec("T-001"), rec(ULID_ID, depends_on=["T-001"]))
        cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": PATTERN})
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_e_vacuous_pattern_refused(self):
        self.tasks(rec(ULID_ID))
        for vacuous in (".*", ".+", r"[^\n]*", "(?s).*"):
            cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": vacuous})
            self.assertNotEqual(cp.returncode, 0, vacuous)
            self.assertIn("would accept any id", cp.stdout + cp.stderr, vacuous)

    def test_f_bad_regex_refused(self):
        self.tasks(rec(ULID_ID))
        cp = self.art("validate", env_extra={"DEVLOOP_TASK_ID_RE": "task_[0-9"})
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("invalid regex", cp.stdout + cp.stderr)

    def test_g_export_schema_carries_the_project_shape(self):
        self.tasks(rec(ULID_ID))
        cp = self.art("export-openai", env_extra={"DEVLOOP_TASK_ID_RE": PATTERN})
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn(PATTERN, cp.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
