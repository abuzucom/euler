"""Tests for the deterministic checkers behind scripts/check_code_quality.py.

Each check has one positive fixture that must produce its class and one
negative fixture that must not. Fixture strings hold the flagged patterns on
purpose. The repository self-scan skips tests/ for that reason.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import quality_checks  # resolved through the path set above

MARKER = "TO" + "DO"
NOQA = "# no" + "qa"
# Nesting deep enough to exhaust the Python and TOML parsers.
DEEP_PYTHON = "x = " + "-" * 100_000 + "1\n"
TOML_DEPTH = 5_000
DEEP_TOML = "a = " + "[" * TOML_DEPTH + "]" * TOML_DEPTH + "\n"


class CheckerCase(unittest.TestCase):
    """Base case running checks against files in a temporary root."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def write_files(self, files: dict[str, str]) -> list[Path]:
        """Write fixture files and return their paths."""
        paths = []
        for relative, content in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            paths.append(path)
        return paths

    def classes_for(self, check: str, files: dict[str, str], changed: list[str] | None = None) -> set[str]:
        """Run one check and return the class IDs it reports."""
        paths = self.write_files(files)
        findings = quality_checks.run_checks([check], paths, self.root, changed=changed)
        return {finding.class_id for finding in findings}

    def assert_flags(self, check: str, class_id: str, files: dict[str, str], changed: list[str] | None = None) -> None:
        self.assertIn(class_id, self.classes_for(check, files, changed))

    def assert_clean(self, check: str, class_id: str, files: dict[str, str], changed: list[str] | None = None) -> None:
        self.assertNotIn(class_id, self.classes_for(check, files, changed))


class RegexCheckTest(CheckerCase):
    def test_nested_quantifier_python(self) -> None:
        self.assert_flags("regex", "Q3", {"a.py": 'import re\nPATTERN = re.compile(r"(a+)+$")\n'})

    def test_nested_quantifier_js(self) -> None:
        self.assert_flags("regex", "Q3", {"a.js": "const pattern = /^(\\w+\\s?)*$/;\n"})

    def test_overlapping_alternation(self) -> None:
        self.assert_flags("regex", "Q3", {"a.py": 'import re\nre.match(r"(a|a)*b", text)\n'})

    def test_linear_pattern_clean(self) -> None:
        self.assert_clean("regex", "Q3", {"a.py": 'import re\nre.match(r"^[a-z]+(-[a-z]+)?$", text)\n'})


class DeadCodeCheckTest(CheckerCase):
    def test_statement_after_return(self) -> None:
        self.assert_flags("dead-code", "Q5", {"a.py": "def f():\n    return 1\n    value = 2\n"})

    def test_constant_false_branch(self) -> None:
        self.assert_flags("dead-code", "Q5", {"a.py": "if False:\n    run()\n"})

    def test_live_code_clean(self) -> None:
        self.assert_clean("dead-code", "Q5", {"a.py": "def f(x):\n    if x:\n        return 1\n    return 2\n"})


class IterationMutationCheckTest(CheckerCase):
    def test_remove_during_iteration(self) -> None:
        source = "def f(items):\n    for item in items:\n        if item:\n            items.remove(item)\n"
        self.assert_flags("iteration-mutation", "Q8", {"a.py": source})

    def test_del_during_dict_iteration(self) -> None:
        source = "def f(table):\n    for key in table.keys():\n        del table[key]\n"
        self.assert_flags("iteration-mutation", "Q8", {"a.py": source})

    def test_iterating_copy_clean(self) -> None:
        source = "def f(items):\n    for item in list(items):\n        items.remove(item)\n"
        self.assert_clean("iteration-mutation", "Q8", {"a.py": source})


class RecursionCheckTest(CheckerCase):
    def test_unbounded_recursion(self) -> None:
        source = "def walk(node):\n    for child in node.children:\n        walk(child)\n"
        self.assert_flags("recursion", "Q9", {"a.py": source})

    def test_depth_limited_recursion_clean(self) -> None:
        source = (
            "def walk(node, depth=0):\n    if depth > 50:\n        raise ValueError('too deep')\n"
            "    for child in node.children:\n        walk(child, depth + 1)\n"
        )
        self.assert_clean("recursion", "Q9", {"a.py": source})


class ResourceLeakCheckTest(CheckerCase):
    def test_open_without_with(self) -> None:
        self.assert_flags(
            "resource-leak", "Q11", {"a.py": "def f(p):\n    handle = open(p)\n    return handle.read()\n"}
        )

    def test_db_connect_without_close(self) -> None:
        source = "import sqlite3\ndef f():\n    conn = sqlite3.connect('x.db')\n    return conn.execute('select 1')\n"
        self.assert_flags("resource-leak", "Q11", {"a.py": source})

    def test_with_block_clean(self) -> None:
        self.assert_clean(
            "resource-leak", "Q11", {"a.py": "def f(p):\n    with open(p) as handle:\n        return handle.read()\n"}
        )

    def test_finally_close_clean(self) -> None:
        source = "def f(p):\n    handle = open(p)\n    try:\n        return handle.read()\n    finally:\n        handle.close()\n"
        self.assert_clean("resource-leak", "Q11", {"a.py": source})

    def test_returned_resource_clean(self) -> None:
        self.assert_clean("resource-leak", "Q11", {"a.py": "def f(p):\n    return open(p)\n"})


class MutableDefaultCheckTest(CheckerCase):
    def test_list_default(self) -> None:
        self.assert_flags("mutable-default", "Q13", {"a.py": "def f(items=[]):\n    return items\n"})

    def test_none_default_clean(self) -> None:
        self.assert_clean("mutable-default", "Q13", {"a.py": "def f(items=None):\n    return items or []\n"})


class EmptyCatchCheckTest(CheckerCase):
    def test_python_pass_handler(self) -> None:
        self.assert_flags("empty-catch", "M1", {"a.py": "try:\n    run()\nexcept ValueError:\n    pass\n"})

    def test_js_empty_catch(self) -> None:
        self.assert_flags("empty-catch", "M1", {"a.ts": "try {\n  run();\n} catch (err) {\n}\n"})

    def test_handled_exception_clean(self) -> None:
        source = "try:\n    run()\nexcept ValueError as error:\n    log(error)\n    raise\n"
        self.assert_clean("empty-catch", "M1", {"a.py": source})


class MagicNumberCheckTest(CheckerCase):
    def test_unnamed_literal(self) -> None:
        self.assert_flags("magic-number", "M11", {"a.py": "def f(total):\n    return total * 0.0825\n"})

    def test_named_constant_clean(self) -> None:
        source = "TAX_RATE = 0.0825\n\ndef f(total):\n    return total * TAX_RATE - 1\n"
        self.assert_clean("magic-number", "M11", {"a.py": source})


class IncompleteWorkCheckTest(CheckerCase):
    def test_marker_comment(self) -> None:
        self.assert_flags("incomplete-work", "M12", {"a.py": f"def f():\n    return 1  # {MARKER} handle errors\n"})

    def test_stub_body(self) -> None:
        self.assert_flags("incomplete-work", "M12", {"a.py": "def f():\n    pass\n"})

    def test_bare_not_implemented(self) -> None:
        self.assert_flags("incomplete-work", "M12", {"a.py": "def f():\n    raise NotImplementedError\n"})

    def test_abstract_method_clean(self) -> None:
        source = (
            "import abc\n\nclass Base(abc.ABC):\n    @abc.abstractmethod\n    def run(self):\n"
            "        '''Run the job.'''\n"
        )
        self.assert_clean("incomplete-work", "M12", {"a.py": source})


class SuppressedChecksCheckTest(CheckerCase):
    def test_noqa(self) -> None:
        self.assert_flags("suppressed-checks", "M13", {"a.py": f"import os  {NOQA}\n"})

    def test_continue_on_error(self) -> None:
        workflow = "jobs:\n  a:\n    steps:\n      - run: make\n        continue-on-error: true\n"
        self.assert_flags("suppressed-checks", "M13", {".github/workflows/ci.yml": workflow})

    def test_plain_code_clean(self) -> None:
        self.assert_clean("suppressed-checks", "M13", {"a.py": "import os\n"})


class BroadCatchCheckTest(CheckerCase):
    def test_except_exception_without_raise(self) -> None:
        source = "try:\n    run()\nexcept Exception as error:\n    log(error)\n"
        self.assert_flags("broad-catch", "M16", {"a.py": source})

    def test_swallow_reported_under_m1_only(self) -> None:
        self.assert_clean("broad-catch", "M16", {"a.py": "try:\n    run()\nexcept Exception:\n    pass\n"})

    def test_reraise_clean(self) -> None:
        source = "try:\n    run()\nexcept Exception as error:\n    log(error)\n    raise\n"
        self.assert_clean("broad-catch", "M16", {"a.py": source})


class DebugLeftoversCheckTest(CheckerCase):
    def test_breakpoint(self) -> None:
        self.assert_flags("debug-leftovers", "M17", {"a.py": "def f():\n    breakpoint()\n"})

    def test_print_in_library_module(self) -> None:
        self.assert_flags("debug-leftovers", "M17", {"a.py": "def f(x):\n    print(x)\n    return x\n"})

    def test_js_debugger(self) -> None:
        self.assert_flags("debug-leftovers", "M17", {"a.js": "function f() {\n  debugger;\n}\n"})

    def test_cli_print_clean(self) -> None:
        source = "def main():\n    print('ok')\n\nif __name__ == '__main__':\n    main()\n"
        self.assert_clean("debug-leftovers", "M17", {"a.py": source})


class HardcodedEnvCheckTest(CheckerCase):
    def test_internal_url(self) -> None:
        self.assert_flags("hardcoded-env", "M18", {"a.py": 'API = "https://billing.internal.corp/v1"\n'})

    def test_home_path(self) -> None:
        self.assert_flags("hardcoded-env", "M18", {"a.py": 'DATA = "/home/alice/data.csv"\n'})

    def test_documentation_host_clean(self) -> None:
        self.assert_clean("hardcoded-env", "M18", {"a.py": 'SAMPLE = "https://example.com/api"\n'})

    def test_tests_directory_skipped(self) -> None:
        self.assert_clean("hardcoded-env", "M18", {"tests/test_a.py": 'API = "https://billing.internal.corp/v1"\n'})


class UntestedChangesCheckTest(CheckerCase):
    def test_source_without_test(self) -> None:
        self.assert_flags("untested-changes", "C3", {"app/core.py": "X = 1\n"}, changed=["app/core.py"])

    def test_source_with_test_clean(self) -> None:
        files = {"app/core.py": "X = 1\n", "tests/test_core.py": "Y = 1\n"}
        self.assert_clean("untested-changes", "C3", files, changed=["app/core.py", "tests/test_core.py"])

    def test_no_changed_list_clean(self) -> None:
        self.assert_clean("untested-changes", "C3", {"app/core.py": "X = 1\n"})


class UnpinnedCheckTest(CheckerCase):
    def test_caret_range_package_json(self) -> None:
        self.assert_flags("unpinned", "D1", {"package.json": '{"dependencies": {"left-pad": "^1.3.0"}}'})

    def test_requirements_range(self) -> None:
        self.assert_flags("unpinned", "D1", {"requirements.txt": "requests>=2.0\n"})

    def test_pyproject_range(self) -> None:
        self.assert_flags(
            "unpinned", "D1", {"pyproject.toml": '[project]\nname = "x"\ndependencies = ["httpx~=0.27"]\n'}
        )

    def test_cargo_default_caret(self) -> None:
        self.assert_flags("unpinned", "D1", {"Cargo.toml": '[dependencies]\nserde = "1.0"\n'})

    def test_action_tag(self) -> None:
        workflow = "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n"
        self.assert_flags("unpinned", "D1", {".github/workflows/ci.yml": workflow})

    def test_exact_pins_clean(self) -> None:
        files = {
            "package.json": '{"dependencies": {"left-pad": "1.3.0"}}',
            "requirements.txt": "requests==2.32.3\n",
            "Cargo.toml": '[dependencies]\nserde = "=1.0.210"\n',
            ".github/workflows/ci.yml": "      - uses: actions/checkout@" + "a" * 40 + " # v4\n",
        }
        self.assert_clean("unpinned", "D1", files)


class HashedRequirementsCheckTest(CheckerCase):
    def test_hashed_pins_clean(self) -> None:
        requirements = (
            "ruff==0.16.9 \\\n"
            "    --hash=sha256:" + "a" * 64 + " \\\n"
            "    --hash=sha256:" + "b" * 64 + "\n"
            "mypy==2.3.1 \\\n"
            "    --hash=sha256:" + "c" * 64 + "\n"
        )
        self.assert_clean("unpinned", "D1", {"requirements-dev.txt": requirements})

    def test_hashed_range_flagged(self) -> None:
        requirements = "ruff>=0.16 \\\n    --hash=sha256:" + "a" * 64 + "\n"
        self.assert_flags("unpinned", "D1", {"requirements-dev.txt": requirements})


class LockfileDriftCheckTest(CheckerCase):
    def test_manifest_without_lockfile(self) -> None:
        self.assert_flags("lockfile-drift", "D2", {"package.json": '{"dependencies": {"a": "1.0.0"}}'})

    def test_manifest_changed_alone(self) -> None:
        files = {"package.json": "{}", "package-lock.json": "{}"}
        self.assert_flags("lockfile-drift", "D2", files, changed=["package.json"])

    def test_both_changed_clean(self) -> None:
        files = {"package.json": "{}", "package-lock.json": "{}"}
        self.assert_clean("lockfile-drift", "D2", files, changed=["package.json", "package-lock.json"])


class UnusedDepsCheckTest(CheckerCase):
    def test_declared_not_imported(self) -> None:
        files = {"requirements.txt": "requests==2.32.3\n", "app.py": "import json\n"}
        self.assert_flags("unused-deps", "D5", files)

    def test_imported_not_declared(self) -> None:
        files = {"requirements.txt": "", "app.py": "import requests\n"}
        self.assert_flags("unused-deps", "D5", files)

    def test_js_declared_and_imported_clean(self) -> None:
        files = {"package.json": '{"dependencies": {"lodash": "4.17.21"}}', "a.js": "import _ from 'lodash';\n"}
        self.assert_clean("unused-deps", "D5", files)

    def test_dev_requirements_not_runtime_declarations(self) -> None:
        files = {"requirements-dev.txt": "ruff==0.16.9\n", "app.py": "import json\n"}
        self.assert_clean("unused-deps", "D5", files)

    def test_python_mapped_name_clean(self) -> None:
        files = {"requirements.txt": "PyYAML==6.0.2\n", "app.py": "import yaml\n"}
        self.assert_clean("unused-deps", "D5", files)


class ParserLimitTest(CheckerCase):
    def test_deep_python_skipped_without_crash(self) -> None:
        paths = self.write_files({"deep.py": DEEP_PYTHON})
        with contextlib.redirect_stderr(io.StringIO()):
            findings = quality_checks.run_checks(list(quality_checks.CHECKS), paths, self.root)
            self.assertTrue(quality_checks.exceeds_parser_limits(paths[0]))
        self.assertEqual(findings, [])

    def test_deep_toml_skipped_without_crash(self) -> None:
        paths = self.write_files({"pyproject.toml": DEEP_TOML})
        with contextlib.redirect_stderr(io.StringIO()):
            findings = quality_checks.run_checks(["unpinned", "unused-deps"], paths, self.root)
            self.assertTrue(quality_checks.exceeds_parser_limits(paths[0]))
        self.assertEqual(findings, [])

    def test_child_finds_parser_limit_files(self) -> None:
        files = {"deep.py": DEEP_PYTHON, "pyproject.toml": DEEP_TOML, "ok.py": "A = 1\n", "broken.py": "def f(:\n"}
        paths = self.write_files(files)
        found = quality_checks.find_parser_limit_files(paths)
        self.assertEqual(sorted(path.name for path in found), ["deep.py", "pyproject.toml"])

    def test_run_checks_records_parse_failures(self) -> None:
        paths = self.write_files({"deep.py": DEEP_PYTHON, "ok.py": "A = 1\n"})
        failures: list[str] = []
        with contextlib.redirect_stderr(io.StringIO()):
            quality_checks.run_checks(list(quality_checks.CHECKS), paths, self.root, parse_failures=failures)
        self.assertEqual(failures, ["deep.py"])

    def test_unused_deps_skips_deep_python(self) -> None:
        self.write_files({"requirements.txt": "requests==2.32.3\n", "deep.py": DEEP_PYTHON})
        with contextlib.redirect_stderr(io.StringIO()):
            findings = quality_checks.run_checks(["unused-deps"], [self.root], self.root)
        self.assertEqual({finding.class_id for finding in findings}, {"D5"})

    def test_syntax_error_within_parser_limits(self) -> None:
        paths = self.write_files({"broken.py": "def f(:\n", "ok.toml": "a = 1\n"})
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertFalse(quality_checks.exceeds_parser_limits(paths[0]))
        self.assertFalse(quality_checks.exceeds_parser_limits(paths[1]))

    def test_toml_decode_error_within_parser_limits(self) -> None:
        paths = self.write_files({"broken.toml": "a = \n"})
        self.assertFalse(quality_checks.exceeds_parser_limits(paths[0]))


class CommandLineTest(CheckerCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run the CLI against the temporary root."""
        script = REPO_ROOT / "scripts" / "check_code_quality.py"
        command = [sys.executable, str(script), *args, "--root", str(self.root)]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_blocking_finding_fails(self) -> None:
        self.write_files({"a.py": "try:\n    run()\nexcept ValueError:\n    pass\n"})
        result = self.run_cli("empty-catch", str(self.root / "a.py"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("M1", result.stdout)

    def test_warning_only_passes(self) -> None:
        self.write_files({"a.py": "def f(items=[]):\n    return items\n"})
        result = self.run_cli("mutable-default", str(self.root / "a.py"))
        self.assertEqual(result.returncode, 0)
        self.assertIn("Q13", result.stdout)

    def test_json_output_assigns_ids(self) -> None:
        self.write_files({"a.py": "def f(items=[]):\n    return items\n"})
        result = self.run_cli("all", str(self.root / "a.py"), "--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["id"], "P1")
        self.assertIn("blocking", payload[0])

    def test_added_lines_filter(self) -> None:
        self.write_files({"a.py": "def f(items=[]):\n    return items\n\ndef g(values={}):\n    return values\n"})
        added = self.root / "added.json"
        added.write_text(json.dumps({"a.py": [4]}), encoding="utf-8")
        result = self.run_cli("mutable-default", str(self.root / "a.py"), "--json", "--added-lines", str(added))
        lines = [item["line"] for item in json.loads(result.stdout)]
        self.assertEqual(lines, [4])

    def test_path_outside_root_rejected(self) -> None:
        result = self.run_cli("all", str(REPO_ROOT / "README.md"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the repository root", result.stderr)


if __name__ == "__main__":
    unittest.main()
