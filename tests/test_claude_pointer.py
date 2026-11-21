#!/usr/bin/env python3
"""Control: the Claude pointer actually imports the constitution (stdlib only).

The pointer lives at .claude/CLAUDE.md (a root CLAUDE.md fails `claude plugin validate --strict`).
Claude Code resolves an `@` import against the IMPORTING file's directory, so a bare `@AGENTS.md`
there names .claude/AGENTS.md, which does not exist, and AGENTS.md silently stops loading. That
happened once: nothing failed, the constitution was simply absent from every later session.

Asserts:
  (a) .claude/CLAUDE.md exists, and no CLAUDE.md sits at the root
  (b) it holds at least one `@` import, and every one resolves, from .claude/, to an existing file
  (c) one of them is the repository's own AGENTS.md
  (d) the pointer stays a pointer: no non-blank line other than imports and HTML comments

Negative control: change the import to `@AGENTS.md` and (b) and (c) fail.

Run: python3 tests/test_claude_pointer.py
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
POINTER = REPO / ".claude" / "CLAUDE.md"


def imports(text: str) -> list[str]:
    return [ln.strip()[1:].strip() for ln in text.splitlines() if ln.strip().startswith("@")]


class ClaudePointer(unittest.TestCase):
    def test_a_location(self):
        self.assertTrue(POINTER.is_file(), f"{POINTER} is missing")
        self.assertFalse((REPO / "CLAUDE.md").exists(), "a root CLAUDE.md fails strict plugin validation")

    def test_b_every_import_resolves_from_its_own_directory(self):
        targets = imports(POINTER.read_text("utf-8"))
        self.assertTrue(targets, ".claude/CLAUDE.md imports nothing")
        for t in targets:
            self.assertTrue((POINTER.parent / t).resolve().is_file(),
                            f"@{t} resolves to {(POINTER.parent / t).resolve()}, which does not exist")

    def test_c_imports_the_root_constitution(self):
        resolved = {(POINTER.parent / t).resolve() for t in imports(POINTER.read_text("utf-8"))}
        self.assertIn((REPO / "AGENTS.md").resolve(), resolved)

    def test_d_stays_a_pointer(self):
        body = [ln for ln in POINTER.read_text("utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith(("@", "<!--"))]
        self.assertEqual(body, [], "the pointer carries content; the constitution lives in AGENTS.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
