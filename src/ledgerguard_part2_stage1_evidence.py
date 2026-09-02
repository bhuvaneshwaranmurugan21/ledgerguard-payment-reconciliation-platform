"""Machine-readable evidence helpers for Part 2 Stage 1."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def parse_junit_counts(report: Path) -> dict[str, int]:
    """Aggregate direct JUnit suites without double-counting wrapper totals."""
    root = ET.parse(report).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = list(root.findall("./testsuite"))
    else:
        raise ValueError(f"Unsupported JUnit root element: {root.tag}")
    if not suites:
        raise ValueError("JUnit report contains no test suites")
    counts = {
        name: sum(int(suite.attrib.get(name, 0)) for suite in suites)
        for name in ("tests", "failures", "errors", "skipped")
    }
    if counts["tests"] < counts["failures"] + counts["errors"] + counts["skipped"]:
        raise ValueError("JUnit report test counts are internally inconsistent")
    return counts
