#!/usr/bin/env python3
"""The plugin's SessionStart hook rejoins a MiOS cloud host's tailnet node in every cloud session.

A cloud session provisioned from a MiOS checkout records that checkout in
<MiOS cloud state>/source-root. tailscaled is a process, so a resumed session has lost it;
the plugin hook (loaded in every session) runs that checkout's `bootstrap.sh tailnet`,
detached, so the hook's own timeout never waits on enrollment.

Controls, against a stand-in bootstrap.sh that records its argv and then sleeps:
  positive  CLAUDE_CODE_REMOTE=true with a source-root: bootstrap.sh runs with `tailnet`
  positive  the hook returns at once although bootstrap.sh is still running (detached)
  negative  without CLAUDE_CODE_REMOTE nothing runs
  negative  no source-root (a cloud session not provisioned from MiOS): nothing runs
  positive  the hook prints nothing extra to stdout (stdout becomes session context)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session-start.sh"

STAND_IN = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$(dirname "$0")/argv"
sleep 20
"""


class SessionStartTailnet(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.state = self.tmp / "mios-cloud"
        self.state.mkdir()
        checkout = self.tmp / "MiOS"
        self.boot = checkout / ".devcontainer" / "cloud-shell" / "bootstrap.sh"
        self.boot.parent.mkdir(parents=True)
        self.boot.write_text(STAND_IN)
        self.argv = self.boot.parent / "argv"
        (self.state / "source-root").write_text(f"{checkout}\n")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        subprocess.run(["pkill", "-f", str(self.boot)], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, remote: bool) -> tuple[str, float]:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "CLAUDE_ENV_FILE")}
        env.update(MIOS_DEPLOYMENT_CLOUD_STATE_DIRECTORY=str(self.state), CLAUDE_PLUGIN_ROOT=str(ROOT))
        if remote:
            env["CLAUDE_CODE_REMOTE"] = "true"
        start = time.monotonic()
        res = subprocess.run(["sh", str(HOOK)], env=env, cwd=self.tmp, capture_output=True, text=True, timeout=30)
        took = time.monotonic() - start
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout, took

    def _argv(self, wait: float = 5.0) -> str:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.argv.exists() and self.argv.read_text():
                return self.argv.read_text()
            time.sleep(0.1)
        return ""

    def test_cloud_session_rejoins_detached(self):
        out, took = self.run_hook(remote=True)
        self.assertEqual(out, "")
        self.assertLess(took, 5.0, "the hook waited on bootstrap.sh instead of detaching it")
        self.assertEqual(self._argv(), "tailnet\n")

    def test_local_session_runs_nothing(self):
        out, _ = self.run_hook(remote=False)
        self.assertEqual(out, "")
        self.assertEqual(self._argv(wait=1.5), "")

    def test_cloud_session_without_a_mios_checkout_runs_nothing(self):
        (self.state / "source-root").unlink()
        out, _ = self.run_hook(remote=True)
        self.assertEqual(out, "")
        self.assertEqual(self._argv(wait=1.5), "")


if __name__ == "__main__":
    unittest.main()
