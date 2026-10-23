#!/usr/bin/env python3
"""Run native fixtures and the pinned original/fixed public OpenIBR comparison."""

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_openibr import build

ORIGINAL = "5e2396cef8e57765c6a8fefe34fc379c3a60c163"
FIXED = "0489b0f2c5cea392f6b6b0743dae43a630732e58"


def check_native(output, source, label, expected_commit, compiler):
    library, receipt = build(source, output / label, compiler, expected_commit)
    if receipt["source_commit"] != expected_commit:
        raise ValueError(f"unexpected {label} source commit")
    report_path = output / f"{label}-report.json"
    command = [sys.executable, "-B", "-m", "inverter_interface_checks", "--library", str(library),
               "--adapter", "openibr-1.1", "--output", str(report_path),
               "--build-receipt", str(output / label / "build.json")]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
    (output / f"{label}-checker.log").write_bytes(completed.stdout + completed.stderr)
    if not report_path.exists():
        raise ValueError(f"{label} checker produced no report")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report["summary"]["complete"]:
        raise ValueError(f"{label} checker suite is incomplete")
    failed = [item["case"]["id"] for item in report["cases"] if not item["ok"]]
    if label == "original":
        if completed.returncode != 1 or failed != [f"parameter[{index}]/nan" for index in range(3)]:
            raise ValueError("original library did not reproduce exactly the three NaN failures")
    elif completed.returncode != 0 or failed:
        raise ValueError("fixed library failed the parameter contract")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--fixed", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cc", default=os.environ.get("CC", "clang"))
    args = parser.parse_args()
    if struct.calcsize("P") != 8:
        parser.error("native checks require 64-bit Python")
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("output directory already exists")
    output.mkdir(parents=True)
    try:
        completed = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
                                   cwd=ROOT, capture_output=True, timeout=180)
        (output / "fixtures.log").write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise ValueError("native fixture tests failed")
        original = check_native(output, args.original, "original", ORIGINAL, args.cc)
        fixed = check_native(output, args.fixed, "fixed", FIXED, args.cc)
        if original["metadata"]["metadata"] != fixed["metadata"]["metadata"]:
            raise ValueError("public model metadata changed between original and fixed builds")
        summary = {"ok": True, "scope": "native loader, metadata and parameter validation",
                   "original": original["summary"], "fixed": fixed["summary"],
                   "metadata_identical": True}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print("Native fixture checks and public original/fixed comparison passed.")


if __name__ == "__main__":
    main()
