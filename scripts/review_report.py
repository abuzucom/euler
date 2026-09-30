"""Parse the final line and VERDICT_JSON companion of a QUALITY.md report."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

FINAL_LINE = re.compile(r"^(?P<label>VERDICT|RISK \(partial\)|RISK):\s*(?P<value>\S.*)$")
JSON_PREFIX = "VERDICT_JSON:"


@dataclass(frozen=True)
class ParsedReport:
    """The machine-relevant parts of one review report."""

    label: str | None
    value: str | None
    token: str | None
    final_line_count: int
    payload: dict | None
    json_error: str | None


def parse_payload(lines: list[str]) -> tuple[dict | None, str | None]:
    """Return the last VERDICT_JSON object and any parse error."""
    candidates = [line for line in lines if line.startswith(JSON_PREFIX)]
    if not candidates:
        return None, "missing VERDICT_JSON line"
    try:
        payload = json.loads(candidates[-1][len(JSON_PREFIX) :].strip())
    except json.JSONDecodeError as error:
        return None, f"VERDICT_JSON is not valid JSON: {error}"
    if not isinstance(payload, dict):
        return None, "VERDICT_JSON must be a JSON object"
    return payload, None


def parse_report(text: str) -> ParsedReport:
    """Return the parsed final line and VERDICT_JSON payload."""
    lines = [line.strip() for line in text.splitlines()]
    matches = [match for match in (FINAL_LINE.match(line) for line in lines) if match]
    payload, json_error = parse_payload(lines)
    if not matches:
        return ParsedReport(None, None, None, 0, payload, json_error)
    last = matches[-1]
    token = last.group("value").split()[0]
    return ParsedReport(last.group("label"), last.group("value"), token, len(matches), payload, json_error)
