"""Project-level checks for dependencies and test coverage of changes."""

from __future__ import annotations

import ast
import json
import re
import sys
import tomllib
from pathlib import Path

from .common import (
    JS_SUFFIXES,
    PARSER_LIMIT_ERRORS,
    PYTHON_SUFFIXES,
    SOURCE_SUFFIXES,
    Finding,
    is_test_path,
    parse_python,
    read_text,
)

EXACT_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
USES_LINE = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)")
REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
HASH_OPTION = re.compile(r"\s--hash=\S+")
EXACT_REQUIREMENT = re.compile(r"^[A-Za-z0-9._-]+(?:\[[^\]]*\])?\s*==\s*[^=*,;\s]+\s*(?:;.*)?$")
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s+|\brequire\(\s*)['"]([^'"]+)['"]""")
PACKAGE_JSON_SECTIONS = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")
CARGO_SECTIONS = ("dependencies", "dev-dependencies", "build-dependencies")
LOCKFILES = {
    "package.json": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "bun.lockb"),
    "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock"),
    "Cargo.toml": ("Cargo.lock",),
    "go.mod": ("go.sum",),
    "Pipfile": ("Pipfile.lock",),
}
LOCAL_SPEC_PREFIXES = ("file:", "workspace:", "link:", "portal:")
IMPORT_NAME_OVERRIDES = {
    "pyyaml": "yaml",
    "beautifulsoup4": "bs4",
    "pillow": "PIL",
    "scikit-learn": "sklearn",
    "python-dateutil": "dateutil",
    "opencv-python": "cv2",
    "protobuf": "google",
    "attrs": "attr",
}
SCOPED_PACKAGE_SEGMENTS = 2
NODE_BUILTINS = frozenset({
    "assert",
    "buffer",
    "child_process",
    "crypto",
    "events",
    "fs",
    "http",
    "https",
    "net",
    "os",
    "path",
    "process",
    "querystring",
    "readline",
    "stream",
    "timers",
    "tls",
    "url",
    "util",
    "worker_threads",
    "zlib",
})


def load_toml(path: Path) -> dict:
    """Return parsed TOML, or an empty table with a warning."""
    text = read_text(path)
    try:
        return tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as error:
        sys.stderr.write(f"warning: skipped {path}: {error}. Fix the TOML syntax to check it.\n")
    except PARSER_LIMIT_ERRORS as error:
        sys.stderr.write(f"warning: skipped {path}: {type(error).__name__}. Reduce the nesting to check it.\n")
    return {}


def load_json(path: Path) -> dict:
    """Return a parsed JSON object, or an empty object with a warning."""
    text = read_text(path)
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError as error:
        sys.stderr.write(f"warning: skipped {path}: {error}. Fix the JSON syntax to check it.\n")
        return {}
    return data if isinstance(data, dict) else {}


def normalize_package(name: str) -> str:
    """Return a PEP 503 normalized package name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def unpinned_package_json(relative: str, path: Path) -> list[Finding]:
    """D1 for package.json version specs."""
    data = load_json(path)
    findings = []
    for section in PACKAGE_JSON_SECTIONS:
        for name, raw_spec in (data.get(section) or {}).items():
            spec = str(raw_spec)
            pinned_git = "#" in spec and FULL_SHA.match(spec.rsplit("#", 1)[1])
            if EXACT_SEMVER.match(spec) or pinned_git or spec.startswith(LOCAL_SPEC_PREFIXES):
                continue
            findings.append(Finding(relative, 1, "D1", f"'{name}' uses unpinned spec '{spec}'", False))
    return findings


def join_requirement_lines(text: str) -> list[tuple[int, str]]:
    """Return logical requirement lines with continuations joined and hash options removed."""
    logical: list[tuple[int, list[str]]] = []
    continued = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.rstrip()
        if not continued:
            logical.append((number, []))
        logical[-1][1].append(stripped.removesuffix("\\"))
        continued = stripped.endswith("\\")
    return [(number, HASH_OPTION.sub("", " " + " ".join(parts)).strip()) for number, parts in logical]


def unpinned_requirement_lines(relative: str, lines: list[tuple[int, str]]) -> list[Finding]:
    """D1 for PEP 508 requirement strings."""
    findings = []
    for number, line in lines:
        requirement = line.split(" #", 1)[0].strip()
        if not requirement or requirement.startswith(("#", "-")):
            continue
        if EXACT_REQUIREMENT.match(requirement) or ("@" in requirement and "#sha256=" in requirement):
            continue
        findings.append(Finding(relative, number, "D1", f"unpinned requirement '{requirement}'", False))
    return findings


def unpinned_poetry(relative: str, poetry: dict) -> list[Finding]:
    """D1 for tool.poetry.dependencies tables."""
    findings = []
    for name, spec in poetry.items():
        if name == "python" or (isinstance(spec, dict) and ("path" in spec or "rev" in spec)):
            continue
        version = spec.get("version", "") if isinstance(spec, dict) else str(spec)
        if not EXACT_SEMVER.match(version.lstrip("=")) or version.startswith(("^", "~")):
            findings.append(Finding(relative, 1, "D1", f"'{name}' uses unpinned spec '{version}'", False))
    return findings


def unpinned_pyproject(relative: str, path: Path) -> list[Finding]:
    """D1 for pyproject.toml project and poetry dependencies."""
    data = load_toml(path)
    project = data.get("project") or {}
    requirements = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        requirements.extend(extra)
    poetry = ((data.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    findings = unpinned_requirement_lines(relative, [(1, item) for item in requirements])
    return findings + unpinned_poetry(relative, poetry)


def unpinned_cargo(relative: str, path: Path) -> list[Finding]:
    """D1 for Cargo.toml. Cargo treats a bare version as a caret range."""
    data = load_toml(path)
    findings = []
    for section in CARGO_SECTIONS:
        for name, spec in (data.get(section) or {}).items():
            if isinstance(spec, dict) and ("path" in spec or "rev" in spec):
                continue
            version = spec.get("version", "") if isinstance(spec, dict) else str(spec)
            if not version.startswith("="):
                findings.append(Finding(relative, 1, "D1", f"'{name}' uses unpinned spec '{version}'", False))
    return findings


def unpinned_workflow(relative: str, text: str) -> list[Finding]:
    """D1 for workflow and action uses: references."""
    findings = []
    for number, line in enumerate(text.splitlines(), 1):
        match = USES_LINE.match(line)
        if not match or match.group(1).startswith("./"):
            continue
        reference = match.group(1)
        if reference.startswith("docker://"):
            pinned = "@sha256:" in reference
        else:
            pinned = "@" in reference and bool(FULL_SHA.match(reference.rsplit("@", 1)[1]))
        if not pinned:
            findings.append(Finding(relative, number, "D1", f"'{reference}' is not pinned to a full SHA", False))
    return findings


def check_unpinned(path: Path, relative: str, text: str) -> list[Finding]:
    """D1: dispatch on the manifest or workflow type."""
    name = path.name
    if name == "package.json":
        return unpinned_package_json(relative, path)
    if name.startswith("requirements") and name.endswith(".txt"):
        return unpinned_requirement_lines(relative, join_requirement_lines(text))
    if name == "pyproject.toml":
        return unpinned_pyproject(relative, path)
    if name == "Cargo.toml":
        return unpinned_cargo(relative, path)
    if ".github/" in "/" + relative and path.suffix in (".yml", ".yaml"):
        return unpinned_workflow(relative, text)
    return []


def lockfile_finding(root: Path, relative: str, changed: set[str] | None) -> Finding | None:
    """Return the D2 finding for one manifest, or None."""
    path = Path(relative)
    siblings = [(path.parent / lockfile).as_posix() for lockfile in LOCKFILES[path.name]]
    present = [sibling for sibling in siblings if (root / sibling).is_file()]
    if not present:
        return Finding(relative, 1, "D2", "manifest has no lockfile", False)
    if changed is None:
        return None
    manifest_changed = relative in changed
    if manifest_changed == any(sibling in changed for sibling in present):
        return None
    message = "manifest changed without its lockfile" if manifest_changed else "lockfile changed alone"
    return Finding(relative, 1, "D2", message, False)


def check_lockfile_drift(root: Path, relatives: list[str], changed: list[str] | None) -> list[Finding]:
    """D2: manifests without a lockfile, and manifest or lockfile changes made alone."""
    changed_set = set(changed) if changed is not None else None
    candidates = [relative for relative in relatives if Path(relative).name in LOCKFILES]
    findings = [lockfile_finding(root, relative, changed_set) for relative in candidates]
    return [finding for finding in findings if finding is not None]


def declared_python(root: Path) -> dict[str, str]:
    """Return declared Python packages as import name to manifest path."""
    declared: dict[str, str] = {}
    # Only runtime requirements declare imports. Dev tool files such as
    # requirements-dev.txt list tools that code never imports.
    for manifest in sorted(root.glob("requirements.txt")):
        for line in (read_text(manifest) or "").splitlines():
            match = REQUIREMENT_NAME.match(line)
            if match and not line.lstrip().startswith(("#", "-")):
                declared[import_name(match.group(1))] = manifest.name
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        for requirement in (load_toml(pyproject).get("project") or {}).get("dependencies") or []:
            match = REQUIREMENT_NAME.match(requirement)
            if match:
                declared[import_name(match.group(1))] = pyproject.name
    return declared


def import_name(package: str) -> str:
    """Return the usual import name for a distribution name."""
    normalized = normalize_package(package)
    return IMPORT_NAME_OVERRIDES.get(normalized, normalized.replace("-", "_"))


def python_imports(path: Path) -> set[str]:
    """Return top-level module names imported by one Python file."""
    tree = parse_python(path, read_text(path) or "")
    if tree is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def local_modules(root: Path) -> set[str]:
    """Return top-level module names defined inside the repository."""
    names = {path.stem for path in root.rglob("*.py")}
    names.update(path.parent.name for path in root.rglob("__init__.py"))
    return names


def first_import_locations(root: Path, sources: list[Path]) -> dict[str, str]:
    """Return each imported Python module with the first file importing it."""
    imported: dict[str, str] = {}
    for path in sources:
        for name in python_imports(path):
            imported.setdefault(name, path.relative_to(root).as_posix())
    return imported


def unused_python(root: Path, sources: list[Path]) -> list[Finding]:
    """D5 for Python: declared but unused, and imported but undeclared."""
    has_manifest = (root / "requirements.txt").is_file() or (root / "pyproject.toml").is_file()
    if not has_manifest:
        return []
    declared = declared_python(root)
    imported = first_import_locations(root, sources)
    ignored = set(sys.stdlib_module_names) | local_modules(root)
    findings = [
        Finding(manifest, 1, "D5", f"'{name}' is declared but never imported", False)
        for name, manifest in sorted(declared.items())
        if name not in imported
    ]
    for name, location in sorted(imported.items()):
        if name not in ignored and name not in declared:
            findings.append(Finding(location, 1, "D5", f"'{name}' is imported but not declared", False))
    return findings


def js_package(specifier: str) -> str | None:
    """Return the package name of a bare import specifier."""
    if specifier.startswith((".", "/", "node:")):
        return None
    parts = specifier.split("/")
    name = "/".join(parts[:SCOPED_PACKAGE_SEGMENTS]) if specifier.startswith("@") else parts[0]
    return None if name in NODE_BUILTINS else name


def first_js_package_locations(root: Path, sources: list[Path]) -> dict[str, str]:
    """Return each imported npm package with the first file importing it."""
    imported: dict[str, str] = {}
    for path in sources:
        for match in JS_IMPORT.finditer(read_text(path) or ""):
            package = js_package(match.group(1))
            if package:
                imported.setdefault(package, path.relative_to(root).as_posix())
    return imported


def unused_js(root: Path, sources: list[Path]) -> list[Finding]:
    """D5 for JavaScript and TypeScript against package.json."""
    manifest = root / "package.json"
    if not manifest.is_file():
        return []
    data = load_json(manifest)
    declared = {name for section in PACKAGE_JSON_SECTIONS for name in (data.get(section) or {})}
    imported = first_js_package_locations(root, sources)
    findings = [
        Finding("package.json", 1, "D5", f"'{name}' is declared but never imported", False)
        for name in sorted(declared - set(imported))
        if not name.startswith("@types/")
    ]
    for name, location in sorted(imported.items()):
        if name not in declared:
            findings.append(Finding(location, 1, "D5", f"'{name}' is imported but not declared", False))
    return findings


def check_unused_deps(root: Path, relatives: list[str], changed: list[str] | None) -> list[Finding]:
    """D5: compare manifests with imports across the scanned sources."""
    paths = [root / relative for relative in relatives]
    python_sources = [path for path in paths if path.suffix in PYTHON_SUFFIXES]
    js_sources = [path for path in paths if path.suffix in JS_SUFFIXES]
    return unused_python(root, python_sources) + unused_js(root, js_sources)


def check_untested_changes(root: Path, relatives: list[str], changed: list[str] | None) -> list[Finding]:
    """C3: source changes in a PR without any test change."""
    if not changed:
        return []
    sources = [item for item in changed if Path(item).suffix in SOURCE_SUFFIXES and not is_test_path(item)]
    tests = [item for item in changed if is_test_path(item)]
    if not sources or tests:
        return []
    return [Finding(sources[0], 1, "C3", f"{len(sources)} source file(s) changed without a test change", False)]
