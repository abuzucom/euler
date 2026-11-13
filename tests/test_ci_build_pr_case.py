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
from unittest import mock

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

    def git_raw(self, *args: str) -> str:
        """Run git in the repository and return stdout without stripping."""
        git = shutil.which("git")
        self.assertIsNotNone(git, "git not found on PATH")
        env = {**os.environ, **GIT_ENV, "GIT_LITERAL_PATHSPECS": "1"}
        result = subprocess.run([str(git), "-C", str(self.repo), *args], capture_output=True, env=env, check=True)
        return result.stdout.decode("utf-8", errors="replace")

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

    def test_default_budget_reviews_a_large_pr_in_one_chunk(self) -> None:
        patches = {f"file{index}.py": "+" + "x" * 249_999 for index in range(3)}
        chunks, oversized = build_pr_case.pack_chunks(
            patches, build_pr_case.MAX_ENVELOPE_BYTES, measure=build_pr_case.escaped_size
        )
        self.assertEqual(chunks, [sorted(patches)])
        self.assertEqual(oversized, [])

    def test_default_budget_still_flags_a_patch_above_it(self) -> None:
        patches = {"huge.py": "+" + "x" * 899_999}
        chunks, oversized = build_pr_case.pack_chunks(
            patches, build_pr_case.MAX_ENVELOPE_BYTES, measure=build_pr_case.escaped_size
        )
        self.assertEqual(chunks, [])
        self.assertEqual(oversized, ["huge.py"])

    def test_escaped_size_counts_json_escapes_and_utf8_bytes(self) -> None:
        self.assertEqual(build_pr_case.escaped_size("ab"), 2)
        self.assertEqual(build_pr_case.escaped_size('"\\\n'), 6)
        self.assertEqual(build_pr_case.escaped_size("\x01"), 6)
        self.assertEqual(build_pr_case.escaped_size("中"), 3)
        self.assertEqual(build_pr_case.escaped_size("\U0001f600"), 4)

    def test_default_budget_keeps_dense_envelopes_under_the_context(self) -> None:
        # Each fixture escapes to about 400,000 bytes. Character counts stay far lower.
        dense = {
            "code.txt": "def handler(event):\n    return {'key': event['value']}\n" * 7_400,
            "cjk.txt": ("中文测试" * 25 + "\n") * 1_320,
            "emoji.txt": ("\U0001f600\U0001f680" * 50 + "\n") * 1_000,
            "escapes.txt": ('\x01"\\\t' * 25 + "\n") * 1_100,
        }
        base = self.commit({"a.txt": "x\n"})
        head = self.commit(dense)
        out_dir = self.build(base, head)
        manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], [])
        self.assertGreater(len(manifest["chunks"]), 1)
        for chunk in manifest["chunks"]:
            envelope_bytes = (out_dir / "envelopes" / chunk["envelope"]).read_bytes()
            self.assertLessEqual(len(envelope_bytes), build_pr_case.MAX_ENVELOPE_BYTES)

    def test_default_budget_flags_a_dense_patch_with_few_characters(self) -> None:
        # 200,000 control characters escape to 1,200,000 bytes.
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"control.txt": ("\x01" * 99 + "\n") * 2_000})
        manifest = json.loads((self.build(base, head) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], ["control.txt"])

    def test_explicit_byte_budget_counts_escaped_bytes(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"one.txt": "\x01\n" * 40, "two.txt": "\x01\n" * 40})
        manifest = json.loads((self.build(base, head, max_bytes=500) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["chunks"]), 2)

    def test_character_and_byte_budgets_together_rejected(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        head = self.commit({"b.txt": "y\n"})
        with self.assertRaises(ValueError):
            self.build(base, head, max_chars=400, max_bytes=400)

    def test_reply_reserve_matches_the_active_profile(self) -> None:
        data = json.loads((REPO_ROOT / "ci" / "model_providers.json").read_text(encoding="utf-8"))
        profile = data["providers"][data["active_provider"]]
        self.assertEqual(build_pr_case.REPLY_TOKENS, profile["max_output_tokens"])

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

    def test_extract_head_writes_exact_blobs(self) -> None:
        contents = {
            "a.py": "\n\nfirst\nsecond\n",
            "dir/b.txt": "no trailing newline",
            "dir/deep/c.bin": b"\n\x00\n1 blob 99\n\xff",
            "empty.txt": "",
        }
        head = self.commit(contents)
        target = Path(self.temp_dir.name) / "tree"
        target.mkdir()
        options = build_pr_case.BuildOptions(self.repo, head, head, target, "", "", 1)
        build_pr_case.extract_head(options, target)
        for name, content in contents.items():
            expected = content if isinstance(content, bytes) else content.encode("utf-8")
            self.assertEqual((target / name).read_bytes(), expected, name)

    def test_single_diff_call_matches_per_file_patches(self) -> None:
        base = self.commit({"mode.sh": "echo hi\n", "keep.txt": "a\n"})
        (self.repo / "mode.sh").chmod(0o755)
        head = self.commit({
            "src/with space.py": "A = 1\n",
            "tab\tname.py": "B = 2\n",
            "fake.txt": "diff --git a/x b/x\n",
            "logo.png": b"\x89PNG\x00\x01",
            "keep.txt": "a\nb\n",
        })
        options = build_pr_case.BuildOptions(self.repo, base, head, Path(self.temp_dir.name), "", "", 1)
        changed, binary, patches, undecodable = build_pr_case.read_diff(options)
        self.assertEqual(undecodable, [])
        self.assertEqual(binary, {"logo.png"})
        self.assertEqual(sorted(changed), sorted([*patches, "logo.png"]))
        self.assertEqual(len(patches), 5)
        for path, patch in patches.items():
            expected = self.git_raw("diff", "--no-color", "--no-renames", base, head, "--", path)
            self.assertEqual(patch, expected, path)

    def test_parse_combined_diff_rejects_truncated_records(self) -> None:
        self.assertIsNone(build_pr_case.parse_combined_diff(b":100644 100644 a b M\0trunc"))

    def test_parse_combined_diff_rejects_count_mismatch(self) -> None:
        output = b":100644 100644 a b M\0one.py\0:100644 100644 c d M\0two.py\0\0diff --git a/one.py b/one.py\n"
        self.assertIsNone(build_pr_case.parse_combined_diff(output))

    def test_parse_combined_diff_splits_well_formed_output(self) -> None:
        output = (
            b":100644 100644 a b M\0one.py\0:100644 100644 c d M\0two.py\0\0"
            b"diff --git a/one.py b/one.py\n+x\ndiff --git a/two.py b/two.py\n+y\n"
        )
        parsed = build_pr_case.parse_combined_diff(output)
        self.assertEqual(
            parsed,
            (
                [b"one.py", b"two.py"],
                [b"diff --git a/one.py b/one.py\n+x\n", b"diff --git a/two.py b/two.py\n+y\n"],
            ),
        )

    def test_deep_python_with_requirements_listed_unreviewed(self) -> None:
        base = self.commit({"requirements.txt": "requests==2.32.3\n"})
        head = self.commit({"deep.py": DEEP_PYTHON})
        manifest = json.loads((self.build(base, head) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["unreviewed"], ["deep.py"])

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

    def test_read_binary_paths_skips_non_utf8(self) -> None:
        base = self.commit({"a.txt": "x\n"})
        git = shutil.which("git")
        self.assertIsNotNone(git, "git not found on PATH")
        env = {**os.environ, **GIT_ENV}
        blob = (
            subprocess
            .run(
                [str(git), "-C", str(self.repo), "hash-object", "-w", "--stdin"],
                input=b"\x00\x01\x02",
                capture_output=True,
                check=True,
                env=env,
            )
            .stdout.decode("ascii")
            .strip()
        )
        tree_entry = b"100644 blob " + blob.encode("ascii") + b"\tbad\xff.bin\n"
        tree = (
            subprocess
            .run(
                [str(git), "-C", str(self.repo), "mktree"],
                input=tree_entry,
                capture_output=True,
                check=True,
                env=env,
            )
            .stdout.decode("ascii")
            .strip()
        )
        head = (
            subprocess
            .run(
                [str(git), "-C", str(self.repo), "commit-tree", tree, "-p", base, "-m", "add binary"],
                capture_output=True,
                check=True,
                env=env,
            )
            .stdout.decode("ascii")
            .strip()
        )
        options = build_pr_case.BuildOptions(self.repo, base, head, Path(self.temp_dir.name), "", "", 1)
        self.assertEqual(build_pr_case.read_binary_paths(options), set())

    def test_parse_added_lines(self) -> None:
        patch = "@@ -1,2 +1,3 @@\n a\n-b\n+c\n+d\n@@ -10 +11,2 @@\n x\n+y\n"
        self.assertEqual(build_pr_case.parse_added_lines(patch), [2, 3, 12])

    def test_parse_added_lines_counts_content_starting_with_plus_plus(self) -> None:
        patch = "diff --git a/a.c b/a.c\n--- a/a.c\n+++ b/a.c\n@@ -1,2 +1,4 @@\n ctx\n+++counter;\n+bad();\n ctx2\n"
        self.assertEqual(build_pr_case.parse_added_lines(patch), [2, 3])

    def test_read_blobs_returns_blob_bodies(self) -> None:
        head = self.commit({"a.txt": "alpha\n"})
        blob_sha = self.git("rev-parse", f"{head}:a.txt").strip()
        bodies = build_pr_case.read_blobs([blob_sha], self.repo)
        self.assertEqual(bodies, [b"alpha\n"])

    def test_read_blobs_rejects_unparsed_trailing_bytes(self) -> None:
        head = self.commit({"a.txt": "alpha\n"})
        blob_sha = self.git("rev-parse", f"{head}:a.txt").strip()
        corrupted_output = f"{blob_sha} blob 6\nalpha\nextra trailing bytes\n".encode("ascii")
        with mock.patch.object(build_pr_case, "run_git", return_value=corrupted_output):
            with self.assertRaises(RuntimeError) as context:
                build_pr_case.read_blobs([blob_sha], self.repo)
            self.assertIn("unparsed trailing bytes", str(context.exception))


if __name__ == "__main__":
    unittest.main()
