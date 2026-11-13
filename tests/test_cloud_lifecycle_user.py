#!/usr/bin/env python3
"""The cloud Fedora prebuild runs the devcontainer lifecycle as the user the Dev
Containers CLI would attach as: remoteUser, else containerUser, else the image's
own USER, else root.

MiOS's devcontainer.json names no remoteUser; its Containerfile ends with
`USER ${MIOS_IDENTITY_USERNAME:-1000}`, so the image's USER is the account its
build created. A prebuild that read remoteUser alone would fall back to root and
run the lifecycle as the wrong account.

This runs the real `dc_json_get` and `run_lifecycle` from
skills/dev-loop/scripts/env/cloud-fedora-setup.sh against a fake container
runtime that records its calls.

Controls:
  positive  no remoteUser, image USER `user`: the lifecycle runs as `user`
            (test_image_user_is_the_default)
  negative  restoring `user=$(dc_json_get remoteUser); user=${user:-root}` makes
            test_image_user_is_the_default fail: the lifecycle runs as root.
  negative  an `image inspect` that fails is not an empty USER: the prebuild
            defers with no run, chown or exec (test_failed_inspect_defers_...);
            discarding the inspect status makes that test fail.

Run: python3 tests/test_cloud_lifecycle_user.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "dev-loop" / "scripts" / "env" / "cloud-fedora-setup.sh"

RUNTIME = r'''#!/bin/sh
# Fake container runtime: record the call, answer the few queries run_lifecycle makes.
printf '%s\n' "$*" >> "$FAKE_CALLS"
case "$1 $2" in
    "image inspect")
        case "$*" in
            *Config.User*)
                [ "$FAKE_INSPECT_FAIL" = 1 ] && { echo "Error: inspect failed" >&2; exit 125; }
                printf '%s\n' "$FAKE_IMAGE_USER" ;;
        esac
        exit 0 ;;
esac
case "$1" in
    run) case "$*" in *--entrypoint\ id*) echo 1000 ;; esac; exit 0 ;;
    exec|commit|rm|tag) exit 0 ;;
esac
exit 2
'''


def _function(source: str, name: str) -> str:
    match = re.search(rf"(?ms)^{name}\(\) \{{.*?^\}}", source)
    if not match:
        raise AssertionError(f"{name}() not found in {SCRIPT}")
    return match.group(0)


class LifecycleUser(unittest.TestCase):
    def _run(self, config: dict, image_user: str = "user", inspect_fails: bool = False
             ) -> tuple[subprocess.CompletedProcess, list[str], str]:
        source = SCRIPT.read_text()
        functions = _function(source, "dc_json_get") + "\n" + _function(source, "run_lifecycle")
        with tempfile.TemporaryDirectory(prefix="cloud-lifecycle-user-") as tmp:
            tmp_path = Path(tmp)
            functions = functions.replace("/var/log/", f"{tmp}/")
            src = tmp_path / "src"
            (src / ".devcontainer").mkdir(parents=True)
            (src / ".devcontainer" / "devcontainer.json").write_text(json.dumps(config))
            runtime = tmp_path / "runtime"
            runtime.write_text(RUNTIME)
            runtime.chmod(0o755)
            calls = tmp_path / "calls"
            env = dict(os.environ, FAKE_CALLS=str(calls), FAKE_IMAGE_USER=image_user,
                       FAKE_INSPECT_FAIL="1" if inspect_fails else "0")
            harness = "\n".join([
                "set -u",
                f'RT="{runtime}"; BUILD_CTX="{tmp}"; DC_NAME=fixture; DC_SRC="{src}"',
                'DC_JSON=.devcontainer/devcontainer.json; DC_BASE=fixture:base; FEDORA_IMAGE=fixture:latest',
                'DC_REPO=https://example.invalid/MiOS.git; LIFECYCLE_ONLY=0; SETUP_T0=0; SCRIPT_CACHE=unused',
                'log() { :; }',
                'chown() { printf "chown %s\\n" "$*" >> "$FAKE_CALLS"; }',
                functions,
                "run_lifecycle",
            ])
            # The script is #!/usr/bin/env bash (it reads $SECONDS).
            result = subprocess.run(["bash", "-c", harness], env=env, capture_output=True, text=True)
            lines = calls.read_text().splitlines() if calls.exists() else []
            status = tmp_path / "fixture.lifecycle"
            return result, lines, status.read_text() if status.exists() else ""

    def _exec_user(self, lines: list[str]) -> str:
        execs = [line.split() for line in lines if line.startswith("exec ")]
        self.assertEqual(1, len(execs), lines)
        return execs[0][execs[0].index("-u") + 1]

    def test_image_user_is_the_default(self):
        result, lines, _ = self._run({"postCreateCommand": "true"}, image_user="user")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("user", self._exec_user(lines))
        self.assertIn("run --rm --entrypoint id fixture:base -u user", lines)

    def test_remote_user_then_container_user_take_precedence(self):
        for config, want in (({"postCreateCommand": "true", "remoteUser": "remote", "containerUser": "cu"}, "remote"),
                             ({"postCreateCommand": "true", "containerUser": "cu"}, "cu")):
            with self.subTest(want=want):
                result, lines, _ = self._run(config, image_user="user")
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(want, self._exec_user(lines))

    def test_no_user_anywhere_is_root(self):
        result, lines, _ = self._run({"postCreateCommand": "true"}, image_user="")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("root", self._exec_user(lines))

    def test_failed_inspect_defers_with_no_lifecycle_effects(self):
        result, lines, status = self._run({"postCreateCommand": "true"}, inspect_fails=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(status.startswith("deferred: could not read the image user of fixture:base"), status)
        effects = [line for line in lines if line.split()[0] in ("run", "exec", "chown", "commit")]
        self.assertEqual([], effects, lines)
        self.assertIn("tag fixture:base fixture:latest", lines)


if __name__ == "__main__":
    unittest.main(verbosity=2)
