"""Check that each reusable-workflow caller grants what the called jobs request.

A called workflow can only narrow the token permissions its caller job grants.
A nested job that requests more makes GitHub refuse the run at startup, before
any job starts. The check reads the YAML text with the standard library because
make check runs without PyYAML.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CALLERS = ("security-review-pr.yml", "quality-review-pr.yml")
JOB_INDENT = 2
KEY_INDENT = 4
LOCAL_USES = re.compile(r"^ {4}uses: \./\.github/workflows/(?P<file>[A-Za-z0-9_.-]+\.yml)\s*$")
PERMISSION_ENTRY = re.compile(r"^\s+(?P<scope>[a-z-]+):\s*(?P<level>read|write|none)\s*$")
LEVEL_RANK = {"none": 0, "read": 1, "write": 2}


def indentation(line: str) -> int:
    """Return the count of leading spaces on one line."""
    return len(line) - len(line.lstrip(" "))


def child_block(lines: list[str], start: int, indent: int) -> list[str]:
    """Return the lines nested deeper than indent after the line at start."""
    block = []
    for line in lines[start + 1 :]:
        if line.strip() and indentation(line) <= indent:
            break
        block.append(line)
    return block


def split_jobs(workflow: str) -> dict[str, list[str]]:
    """Return each job's body lines keyed by job name."""
    lines = workflow.splitlines()
    jobs_index = lines.index("jobs:")
    jobs = {}
    for index in range(jobs_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and indentation(line) == 0:
            break
        if indentation(line) == JOB_INDENT and line.rstrip().endswith(":") and not line.lstrip().startswith("#"):
            jobs[line.strip()[:-1]] = child_block(lines, index, JOB_INDENT)
    return jobs


def parse_permissions(lines: list[str], indent: int) -> dict[str, str] | None:
    """Return the permissions mapping at one indentation level, or None when absent."""
    marker = f"{' ' * indent}permissions:"
    for index, line in enumerate(lines):
        if line.rstrip() == marker:
            entries = (PERMISSION_ENTRY.match(item) for item in child_block(lines, index, indent))
            return {match["scope"]: match["level"] for match in entries if match}
        if line.startswith(marker):
            # An inline value such as {} grants nothing.
            return {}
    return None


def requested_permissions(called: str) -> dict[str, str]:
    """Return the highest level each scope reaches across every called job."""
    requested: dict[str, str] = {}
    for body in split_jobs(called).values():
        for scope, level in (parse_permissions(body, KEY_INDENT) or {}).items():
            if LEVEL_RANK[level] > LEVEL_RANK[requested.get(scope, "none")]:
                requested[scope] = level
    return requested


def missing_grants(granted: dict[str, str], requested: dict[str, str]) -> dict[str, str]:
    """Return the requested scopes that the grant does not cover."""
    return {
        scope: level for scope, level in requested.items() if LEVEL_RANK[granted.get(scope, "none")] < LEVEL_RANK[level]
    }


class ReusableWorkflowPermissionTests(unittest.TestCase):
    """Verify every local reusable-workflow call grants the called jobs' permissions."""

    def test_every_caller_job_covers_the_called_jobs(self) -> None:
        checked = 0
        for caller_name in CALLERS:
            caller = (WORKFLOWS / caller_name).read_text(encoding="utf-8")
            workflow_grant = parse_permissions(caller.splitlines(), 0) or {}
            for job_name, body in split_jobs(caller).items():
                uses = next((match for match in map(LOCAL_USES.match, body) if match), None)
                if uses is None:
                    continue
                called = (WORKFLOWS / uses["file"]).read_text(encoding="utf-8")
                job_grant = parse_permissions(body, KEY_INDENT)
                granted = workflow_grant if job_grant is None else job_grant
                with self.subTest(caller=caller_name, job=job_name):
                    self.assertEqual(missing_grants(granted, requested_permissions(called)), {})
                checked += 1
        self.assertGreaterEqual(checked, len(CALLERS))


if __name__ == "__main__":
    unittest.main()
