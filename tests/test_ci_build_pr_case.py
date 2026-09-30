"""Tests for ci/build_pr_case.py against a temporary git repository."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from ci import build_pr_case  # resolved through the path set above

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}
EVIL_SOURCE = "import os\n\ntry:\n    os.system(input())\nexcept ValueError:\n    pass\n"
# A long unary chain exhausts the Python parser on 3.11 and 3.12.
DEEP_PYTHON = "x = " + "-" * 100_000 + "1\n"


class GitRepoCase(unittest.TestCase):
    """Base case with a two-commit repository."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repo = Path(self.temp_dir.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")

    def git(self, *args: str) -> str:
        """Run git in the repository and return stdout."""
        env = {**os.environ, **GIT_ENV}
        git = shutil.which("git")
        self.assertIsNotNone(git, "git not found on PATH")
        command = [str(git), "-C", str(self.repo), *args]
        result = subprocess.run(command, capture_output=True, text=True, env=env, check=True)
        return result.stdout.strip()

    def commit(self, files: dict[str, str | bytes | None]) -> str:
        """Write, delete, and commit files. Return the commit SHA."""
        for name, content in files.items():
            path = self.repo / name
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "change")
        return self.git("rev-parse", "HEAD")

    def build(self, base: str, head: str, **kwargs: object) -> Path:
        """Run the builder and return the output directory."""
        out_dir = Path(self.temp_dir.name) / "review"
        options = build_pr_case.BuildOptions(
            repo=self.repo,
            base=base,
            head=head,
            out_dir=out_dir,
            title="Title",
            body="Body text",
            pr_number=7,
            **kwargs,
        )
        build_pr_case.build(options)
        return out_dir


class BuildTest(GitRepoCase):
    def test_envelope_holds_diff_and_context(self) -> None:
        base = self.commit({"app.py": "def f():\n    return 1\n"})
        head = self.commit({"app.py": "def f():\n    return 2\n"})
        out_dir = self.build(base, head)
        envelope = json.loads((out_dir / "envelopes" / "001.json").read_text(encoding="utf-8"))
        self.assertEqual(envelope["mode"], "PR")
        self.assertIn("+    return 2", envelope["REVIEW_TARGET"]["files"]["app.py"])
        self.assertIn("Title", envelope["REVIEW_TARGET"]["context"])
        self.assertEqual(envelope["TRUSTED_CONTEXT"]["metadata"]["head_sha"], head)

    def test_prescan_limited_to_added_lines(self) -> None:
        base = self.commit({"app.py": "def f(items=[]):\n    return items\n"})
        head = self.commit({"app.py": "def f(items=[]):\n    return items\n\n\ndef g(values={}):\n    return values\n"})
        prescan = json.loads((self.build(base, head) / "prescan.json").read_text(encoding="utf-8"))
        q13_lines = [item["line"] for item in prescan if item["class"] == "Q13"]
        self.assertEqual(q13_lines, [5])

    def test_blocking_prescan_recorded(self) -> None:
        base = self.commit({"app.py": "X = 1\n"})
        head = self.commit({"app.py": "try:\n    run()\nexcept ValueError:\n    pass\n"})
        prescan = json.loads((self.build(base, head) / "prescan.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["class"] == "M1" and item["blocking"] for item in prescan))

    def test_excluded_paths_skip_prescan(self) -> None:
        base = self.commit({"README.md": "x\n"})
        head = self.commit({"eval/cases/a/input.py": "try:\n    run()\nexcept ValueError:\n    pass\n"})
        prescan = json.loads(
            (self.build(base, head, exclude=["eval/cases/**"]) / "prescan.json").read_text(encoding="utf-8")
        )
        self.assertEqual(prescan, [])

    def test_binary_file_listed_unreviewed(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"logo.png": b"\x89PNG\x00\x01\x02"})
        manifest = json.loads((self.build(base, head) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], ["logo.png"])

    def test_large_diff_splits_into_chunks(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"one.py": "A = 1\n" * 40, "two.py": "B = 1\n" * 40})
        manifest = json.loads((self.build(base, head, max_chars=400) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["chunks"]), 2)

    def test_oversized_single_file_unreviewed(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"huge.py": "C = 1\n" * 400})
        manifest = json.loads((self.build(base, head, max_chars=400) / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("huge.py", manifest["unreviewed"])

    def test_invalid_sha_rejected(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        with self.assertRaises(ValueError):
            self.build(base, "HEAD; rm -rf /")

    def test_filename_with_space_keeps_patch(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"src/evil helper.py": EVIL_SOURCE})
        out_dir = self.build(base, head)
        envelope = json.loads((out_dir / "envelopes" / "001.json").read_text(encoding="utf-8"))
        self.assertIn("os.system(input())", envelope["REVIEW_TARGET"]["files"]["src/evil helper.py"])
        prescan = json.loads((out_dir / "prescan.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["file"] == "src/evil helper.py" and item["blocking"] for item in prescan))

    def test_non_ascii_filename_keeps_patch(self) -> None:
        name = "café.py"
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({name: EVIL_SOURCE})
        out_dir = self.build(base, head)
        envelope = json.loads((out_dir / "envelopes" / "001.json").read_text(encoding="utf-8"))
        self.assertIn("os.system(input())", envelope["REVIEW_TARGET"]["files"][name])
        prescan = json.loads((out_dir / "prescan.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["file"] == name and item["blocking"] for item in prescan))

    def test_non_utf8_filename_listed_unreviewed(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        (self.repo / os.fsdecode(b"bad\xff.py")).write_text(EVIL_SOURCE, encoding="utf-8")
        head = self.commit({})
        manifest = json.loads((self.build(base, head) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], ["bad�.py"])
        self.assertEqual(manifest["chunks"], [])

    def test_empty_patch_split_out(self) -> None:
        patches, empty = build_pr_case.split_empty_patches({"a.py": "+x\n", "b.py": ""})
        self.assertEqual(patches, {"a.py": "+x\n"})
        self.assertEqual(empty, ["b.py"])

    def test_export_ignore_does_not_hide_file(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({".gitattributes": "evil.py export-ignore\n", "evil.py": EVIL_SOURCE})
        prescan = json.loads((self.build(base, head) / "prescan.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["file"] == "evil.py" and item["class"] == "M1" for item in prescan))

    def test_chunks_over_limit_listed_unreviewed(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"one.py": "A = 1\n" * 40, "two.py": "B = 1\n" * 40})
        out_dir = self.build(base, head, max_chars=400, max_chunks=1)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["chunks"]), 1)
        self.assertEqual(manifest["unreviewed"], ["two.py"])

    def test_parser_limit_file_listed_unreviewed(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"deep.py": DEEP_PYTHON})
        manifest = json.loads((self.build(base, head) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], ["deep.py"])

    def test_parse_added_lines(self) -> None:
        patch = "@@ -1,2 +1,3 @@\n a\n-b\n+c\n+d\n@@ -10 +11,2 @@\n x\n+y\n"
        self.assertEqual(build_pr_case.parse_added_lines(patch), [2, 3, 12])


if __name__ == "__main__":
    unittest.main()
