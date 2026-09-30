"""Tests for ci/run_review.py with a scripted model callable."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import review_envelope  # resolved through the path set above

from ci import run_review  # resolved through the path set above


def report(verdict: str, findings: list[dict] | None = None) -> str:
    """Return a structurally valid report."""
    payload = {"schema_version": "1", "mode": "PR", "verdict": verdict, "findings": findings or [], "prescan": []}
    return f"VERDICT: {verdict} - summary\nVERDICT_JSON: {json.dumps(payload)}\n"


class ScriptedModel:
    """Return queued responses and record the case texts."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.case_texts: list[str] = []

    def __call__(self, system_prompt: str, mode: str, case_text: str) -> str:
        self.case_texts.append(case_text)
        return self.responses.pop(0)


class RunReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.review_dir = Path(self.temp_dir.name)

    def write_review(
        self, chunks: list[list[str]], prescan: list[dict] | None = None, unreviewed: list[str] | None = None
    ) -> None:
        """Write envelopes, prescan, and manifest files."""
        envelopes = self.review_dir / "envelopes"
        envelopes.mkdir()
        manifest_chunks = []
        for index, files in enumerate(chunks, 1):
            name = f"{index:03d}.json"
            metadata = {"base_sha": "a" * 40, "head_sha": "b" * 40}
            text = review_envelope.build_envelope("PR", dict.fromkeys(files, "+x\n"), "", [], metadata)
            (envelopes / name).write_text(text, encoding="utf-8")
            manifest_chunks.append({"envelope": name, "files": files})
        changed_files = [path for files in chunks for path in files]
        manifest = {
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "changed_files": changed_files,
            "unreviewed": unreviewed or [],
            "chunks": manifest_chunks,
        }
        (self.review_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.review_dir / "prescan.json").write_text(json.dumps(prescan or []), encoding="utf-8")

    def run_with(self, model: ScriptedModel) -> dict:
        """Run the review and return result.json."""
        run_review.run(self.review_dir, REPO_ROOT / "QUALITY.md", model)
        return json.loads((self.review_dir / "result.json").read_text(encoding="utf-8"))

    def test_clean_approve(self) -> None:
        self.write_review([["app.py"]])
        self.assertEqual(self.run_with(ScriptedModel([report("APPROVE")]))["verdict"], "APPROVE")

    def test_worst_chunk_verdict_wins(self) -> None:
        self.write_review([["a.py"], ["b.py"]])
        m1 = {"severity": "HIGH", "class": "M1", "file": "b.py", "line": 1, "title": "t", "confidence": "certain"}
        result = self.run_with(ScriptedModel([report("APPROVE"), report("BLOCK", [m1])]))
        self.assertEqual(result["verdict"], "BLOCK")

    def test_malformed_output_retried_once(self) -> None:
        self.write_review([["app.py"]])
        model = ScriptedModel(["no verdict", report("APPROVE")])
        self.assertEqual(self.run_with(model)["verdict"], "APPROVE")
        self.assertIn("RETRY", model.case_texts[1])

    def test_second_malformed_output_needs_human(self) -> None:
        self.write_review([["app.py"]])
        self.assertEqual(self.run_with(ScriptedModel(["bad", "still bad"]))["verdict"], "NEEDS-HUMAN")

    def test_blocking_prescan_forces_block(self) -> None:
        prescan = [{"id": "P1", "file": "app.py", "line": 1, "class": "M1", "message": "m", "blocking": True}]
        self.write_review([["app.py"]], prescan=prescan)
        dismissed = report("APPROVE").replace(
            '"prescan": []', '"prescan": [{"id": "P1", "status": "dismissed", "reason": "r"}]'
        )
        self.assertEqual(self.run_with(ScriptedModel([dismissed]))["verdict"], "BLOCK")

    def test_unreviewed_files_force_needs_human(self) -> None:
        self.write_review([["app.py"]], unreviewed=["logo.png"])
        self.assertEqual(self.run_with(ScriptedModel([report("NEEDS-HUMAN")]))["verdict"], "NEEDS-HUMAN")

    def test_model_error_needs_human(self) -> None:
        self.write_review([["app.py"]])

        def failing_model(system_prompt: str, mode: str, case_text: str) -> str:
            raise run_review.ModelCallError("HTTP 503 from provider")

        run_review.run(self.review_dir, REPO_ROOT / "QUALITY.md", failing_model)
        result = json.loads((self.review_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "NEEDS-HUMAN")

    def test_report_fences_model_text(self) -> None:
        self.write_review([["app.py"]])
        self.run_with(ScriptedModel([report("APPROVE") + "```\n"]))
        text = (self.review_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("````", text)
        self.assertIn("VERDICT: APPROVE", text)

    def test_gate(self) -> None:
        self.assertEqual(run_review.gate_status("BLOCK", True), 1)
        self.assertEqual(run_review.gate_status("NEEDS-HUMAN", True), 1)
        self.assertEqual(run_review.gate_status("BLOCK", False), 0)
        self.assertEqual(run_review.gate_status("APPROVE", True), 0)


if __name__ == "__main__":
    unittest.main()
