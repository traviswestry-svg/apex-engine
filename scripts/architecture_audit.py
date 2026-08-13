"""Repository architecture guard for APEX.

This audit is intentionally dependency-free so it can run in CI, locally, or
on Render without importing the application and triggering runtime work.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_ROOT_PYTHON = {
    "apex_engines.py",      # compatibility facade
    "app.py",               # legacy-compatible web module
    "flatfiles_ingest.py",  # operator CLI
    "flatfiles_probe.py",   # operator CLI
    "scanner_worker.py",    # Render worker entry point
    "signal_evaluator.py",  # scanner-integrated evaluator
    "wsgi.py",              # production WSGI entry point
}

REQUIRED_PATHS = {
    "app.py",
    "wsgi.py",
    "requirements.txt",
    "runtime.txt",
    "start_render.sh",
    "engine/__init__.py",
    "engine/application_composition.py",
    "tests",
}



@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    message: str


def _relative(paths: Iterable[Path]) -> list[str]:
    return sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in paths)


def audit_repository() -> list[Finding]:
    findings: list[Finding] = []

    for required in sorted(REQUIRED_PATHS):
        if not (ROOT / required).exists():
            findings.append(Finding("MISSING_REQUIRED_PATH", required, "Required architecture path is missing."))

    for path in ROOT.glob("test_*.py"):
        findings.append(Finding("ROOT_TEST_FILE", path.name, "Tests must live under tests/."))

    for path in ROOT.glob("*.py"):
        if path.name not in ALLOWED_ROOT_PYTHON:
            findings.append(Finding("UNAPPROVED_ROOT_MODULE", path.name, "Move library code into engine/, scripts/, or tools/."))

    duplicate_names: dict[str, list[Path]] = {}
    for path in (ROOT / "tests").glob("test_*.py"):
        duplicate_names.setdefault(path.name.casefold(), []).append(path)
    for paths in duplicate_names.values():
        if len(paths) > 1:
            findings.append(Finding("DUPLICATE_TEST_NAME", ", ".join(_relative(paths)), "Duplicate test filenames create ambiguous collection."))

    return findings


def main() -> int:
    findings = audit_repository()
    if not findings:
        print("APEX architecture audit: PASS")
        return 0
    print(f"APEX architecture audit: FAIL ({len(findings)} finding(s))")
    for finding in findings:
        print(f"- [{finding.code}] {finding.path}: {finding.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
