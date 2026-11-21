#!/usr/bin/env python3
"""The plugin's SessionStart hook revives agy's keyring in a cloud session, for any repo.

In a cloud environment agy survives in the snapshot but its keyring daemon (a process) does not,
and the repo's own SessionStart hook runs only in sessions rooted in this repo. The plugin hook
loads in every session (CLAUDE_CODE_PLUGIN_DIRS), so it revives the daemon and writes the bus
address into CLAUDE_ENV_FILE, which Claude Code sources before every later tool call.

The env file outlives each SessionStart (startup, resume, clear, compact fire the same hook into
the same file), so the hook owns ONE block there, between `# >>> dev-loop keyring` and
`# <<< dev-loop keyring`, replaced on every run. A bare `>>` stacked a pair per run (~150 in one
long session): correct, because the last pair wins, but unbounded.

Controls, against the real dbus-daemon + gnome-keyring (an empty AGY_CLOUD_DIR is a cold start):
  positive  CLAUDE_CODE_REMOTE=true: the env file gets DBUS_SESSION_BUS_ADDRESS, and a shell that
            sources it finds org.freedesktop.secrets owned on that bus
  negative  without CLAUDE_CODE_REMOTE the env file stays empty
  positive  the hook prints nothing extra to stdout (stdout becomes session context)
Skipped, not passed, when agy, dbus-daemon or gnome-keyring-daemon is absent.

Controls on the block, against a stand-in agy-keyring.sh that writes new fake values on every run
(runs everywhere: no agy or keyring stack needed):
  positive  three runs leave exactly one block, holding the third run's values, after the lines
            other writers put there (kept, once each); no temp file is left; stdout stays empty
  negative  the same three runs through the hook with the old `cat "$KE" >> "$CLAUDE_ENV_FILE"`
            line put back fail the same check (three stacked pairs, no block); the real hook is
            byte-identical afterwards
The MiOS tailnet branch of the hook is pointed at an empty state directory in every run here, so
these tests never start a real `bootstrap.sh tailnet`.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session-start.sh"
AGY = Path.home() / ".local" / "bin" / "agy"

BEGIN = "# >>> dev-loop keyring"
END = "# <<< dev-loop keyring"
# The pre-fix write, verbatim: the negative control puts it back.
OLD_WRITE = '  [ -r "$K" ] && (. "$K") >/dev/null 2>&1 && [ -r "$KE" ] && cat "$KE" >> "$CLAUDE_ENV_FILE"\n'

# Sourced by the hook in a subshell, as the real agy-keyring.sh is: every run writes new values.
STAND_IN = """n=$(( $(cat "$AGY_CLOUD_DIR/n" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$AGY_CLOUD_DIR/n"
printf 'export DBUS_SESSION_BUS_ADDRESS="unix:path=/fake/bus-%s"\\n' "$n" > "$AGY_CLOUD_DIR/keyring.env"
printf 'export GNOME_KEYRING_CONTROL="/fake/ctl-%s"\\n' "$n" >> "$AGY_CLOUD_DIR/keyring.env"
"""

# What other SessionStart writers leave in an env file; the last line has no newline on purpose.
FOREIGN = ['export PATH="$HOME/.local/bin:$PATH"', 'export DEVLOOP_OTHER_WRITER=1']


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


@unittest.skipUnless(AGY.exists() and shutil.which("dbus-daemon") and shutil.which("gnome-keyring-daemon")
                     and shutil.which("dbus-send"), "agy or the keyring stack is not installed")
class SessionStartKeyring(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.kr = self.tmp / "kr"
        self.kr.mkdir()
        (self.tmp / "mios-cloud").mkdir()
        self.envf = self.tmp / "env"
        self.envf.write_text("")
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        subprocess.run(["pkill", "-f", f"--address=unix:path={self.kr}/bus"], capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_hook(self, remote: bool) -> str:
        env = {k: v for k, v in os.environ.items() if k not in ("DBUS_SESSION_BUS_ADDRESS", "CLAUDE_CODE_REMOTE")}
        env.update(CLAUDE_ENV_FILE=str(self.envf), AGY_CLOUD_DIR=str(self.kr), CLAUDE_PLUGIN_ROOT=str(ROOT),
                   MIOS_DEPLOYMENT_CLOUD_STATE_DIRECTORY=str(self.tmp / "mios-cloud"))
        if remote:
            env["CLAUDE_CODE_REMOTE"] = "true"
        res = subprocess.run(["sh", str(HOOK)], env=env, cwd=self.tmp, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def test_remote_cold_start_exports_live_bus(self):
        out = self.run_hook(remote=True)
        self.assertEqual(out, "")
        body = self.envf.read_text()
        self.assertIn("export DBUS_SESSION_BUS_ADDRESS=", body)
        probe = subprocess.run(
            ["sh", "-c", f". '{self.envf}'; dbus-send --session --dest=org.freedesktop.DBus --type=method_call "
             "--print-reply /org/freedesktop/DBus org.freedesktop.DBus.NameHasOwner string:org.freedesktop.secrets"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("boolean true", probe.stdout)

    def test_local_session_writes_nothing(self):
        self.run_hook(remote=False)
        self.assertEqual(self.envf.read_text(), "")


class SessionStartKeyringBlock(unittest.TestCase):
    RUNS = 3

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        agy = self.home / ".local" / "bin" / "agy"
        agy.parent.mkdir(parents=True)
        agy.write_text("#!/bin/sh\nexit 0\n")
        agy.chmod(0o755)
        self.plugin = self.tmp / "plugin"
        k = self.plugin / "skills" / "dev-loop" / "scripts" / "env" / "agy-keyring.sh"
        k.parent.mkdir(parents=True)
        k.write_text(STAND_IN)
        self.kr = self.tmp / "kr"
        self.kr.mkdir()
        (self.tmp / "mios-cloud").mkdir()
        self.sess = self.tmp / "session-env"   # Claude Code gives each hook its own file in such a dir
        self.sess.mkdir()
        self.envf = self.sess / "sessionstart-hook-2.sh"
        self.envf.write_text("\n".join(FOREIGN))

    def run_hook(self, hook: Path) -> str:
        env = {k: v for k, v in os.environ.items()
               if k not in ("DBUS_SESSION_BUS_ADDRESS", "GNOME_KEYRING_CONTROL", "CLAUDE_ENV_FILE")}
        env.update(HOME=str(self.home), CLAUDE_CODE_REMOTE="true", CLAUDE_ENV_FILE=str(self.envf),
                   AGY_CLOUD_DIR=str(self.kr), CLAUDE_PLUGIN_ROOT=str(self.plugin),
                   MIOS_DEPLOYMENT_CLOUD_STATE_DIRECTORY=str(self.tmp / "mios-cloud"))
        res = subprocess.run(["sh", str(hook)], env=env, cwd=self.tmp, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return res.stdout

    def old_hook(self) -> Path:
        """A copy of the hook whose block write is replaced by the pre-fix append."""
        lines = HOOK.read_text(encoding="utf-8").splitlines(keepends=True)
        start = [i for i, l in enumerate(lines) if l.startswith('  if [ -r "$K" ] && (. "$K") >/dev/null 2>&1')]
        self.assertEqual(len(start), 1, "plant target (the keyring write) not found exactly once in the hook")
        end = next(i for i in range(start[0], len(lines)) if lines[i] == "  fi\n")
        p = self.tmp / "session-start.old.sh"
        p.write_text("".join(lines[:start[0]] + [OLD_WRITE] + lines[end + 1:]), encoding="utf-8")
        return p

    def problems(self, n: int) -> list[str]:
        """Everything wrong with the env file after n runs; empty means exactly one current block."""
        body = self.envf.read_text()
        lines = body.splitlines()
        bad = []
        for marker in (BEGIN, END):
            if lines.count(marker) != 1:
                bad.append(f"{lines.count(marker)} {marker!r} lines, want 1")
        for var in ("DBUS_SESSION_BUS_ADDRESS", "GNOME_KEYRING_CONTROL"):
            c = sum(l.startswith(f"export {var}=") for l in lines)
            if c != 1:
                bad.append(f"{c} export {var}= lines, want 1")
        if not bad:
            block = lines[lines.index(BEGIN) + 1:lines.index(END)]
            if block != (self.kr / "keyring.env").read_text().splitlines():
                bad.append("the block does not hold the latest keyring.env")
            if f"/fake/bus-{n}" not in "\n".join(block):
                bad.append(f"the block does not hold run {n}'s values")
            if lines[:lines.index(BEGIN)] != FOREIGN:
                bad.append("the other writers' lines were not kept, once each, ahead of the block")
        live = subprocess.run(["sh", "-c", '. "$1"; printf %s "$DBUS_SESSION_BUS_ADDRESS"', "sh", str(self.envf)],
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.home)},
                              capture_output=True, text=True, timeout=30)
        if live.returncode != 0 or live.stdout != f"unix:path=/fake/bus-{n}":
            bad.append(f"sourcing the file does not yield run {n}'s bus")
        return bad

    def test_three_runs_leave_one_block_with_the_latest_values(self):
        for _ in range(self.RUNS):
            self.assertEqual(self.run_hook(HOOK), "", "the hook must print nothing (stdout becomes context)")
        self.assertEqual((self.kr / "n").read_text().strip(), str(self.RUNS), "the stand-in did not run every time")
        self.assertEqual(self.problems(self.RUNS), [])
        self.assertEqual(sorted(os.listdir(self.sess)), [self.envf.name], "a temp file was left beside the env file")

    def test_the_old_append_fails_the_same_check(self):
        before = sha256(HOOK)
        old = self.old_hook()
        for _ in range(self.RUNS):
            self.run_hook(old)
        bad = self.problems(self.RUNS)
        self.assertIn(f"0 {BEGIN!r} lines, want 1", bad)
        self.assertTrue(any(p.endswith(" export DBUS_SESSION_BUS_ADDRESS= lines, want 1") for p in bad), bad)
        # One pair per run, the first glued onto the newline-less foreign line (a second defect of >>).
        self.assertEqual(self.envf.read_text().count("export DBUS_SESSION_BUS_ADDRESS="), self.RUNS)
        self.assertEqual(sha256(HOOK), before, "the real hook must be untouched")


if __name__ == "__main__":
    unittest.main()
