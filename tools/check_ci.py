#!/usr/bin/env python3
"""Retain native ABI, fixture and pinned OpenIBR parameter-contract evidence."""

import argparse
import json
import math
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.build_openibr import build

ORIGINAL = "5e2396cef8e57765c6a8fefe34fc379c3a60c163"
FIXED = "0489b0f2c5cea392f6b6b0743dae43a630732e58"
NAN_CASES = [f"parameter[{index}]/nan" for index in range(3)]
CASE_IDS = ["defaults", *[f"parameter[{index}]/{name}" for index in range(3)
             for name in ("minimum", "maximum", "below_minimum", "above_maximum", "nan",
                          "positive_infinity", "negative_infinity")], "null_instance", "null_parameters"]
BASE_CHECKS = {"return_code", "Instance/guards", "instance_fields_unchanged",
               *[f"{buffer}/{check}" for buffer in ("ExternalInputs", "ExternalOutputs", "Parameters",
                  "IntStates", "FloatStates", "DoubleStates") for check in ("guards", "unchanged")]}


def saved_run(output, label, arguments, expected=0, timeout=150, compiler=None):
    command = [sys.executable, "-B", *arguments]
    environment = dict(os.environ, CC=compiler) if compiler else None
    with (output / f"{label}.log").open("wb") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout, env=environment)
    if result.returncode != expected:
        raise ValueError(f"{label}: expected exit {expected}, got {result.returncode}")
    return {"check": label, "command": command, "exit_code": result.returncode,
            "expected_exit_code": expected, "timeout_seconds": timeout}


def read_report(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    if (report.get("schema") != "inverter-interface-report/2"
            or not report["metadata"]["ok"] or not report["summary"]["complete"]
            or report["unexecuted_case_ids"]):
        raise ValueError("native report is incomplete or has the wrong schema")
    return report


def failures(call):
    return [check["check"] for check in call["checks"] if not check["ok"]]


def expected_cases(metadata):
    # This oracle is deliberately separate from the checker's case planner.
    cases = [{"id": "defaults", "kind": "valid"}]
    for index, row in enumerate(metadata["parameters"]):
        if row["name"] != ("H", "D", "kDroop")[index] or row["datatype"] != 9 or row["fixed"]:
            raise ValueError("pinned OpenIBR parameter profile changed")
        values = [("minimum", row["minimum"], "valid"), ("maximum", row["maximum"], "valid"),
                  ("below_minimum", math.nextafter(row["minimum"], -math.inf), "invalid"),
                  ("above_maximum", math.nextafter(row["maximum"], math.inf), "invalid"),
                  ("nan", "nan", "invalid"), ("positive_infinity", "inf", "invalid"),
                  ("negative_infinity", "-inf", "invalid")]
        for label, value, kind in values:
            cases.append({"id": f"parameter[{index}]/{label}", "parameter": row["name"],
                          "index": index, "value": value, "kind": kind})
    cases.extend([{"id": "null_instance", "kind": "null_instance"},
                  {"id": "null_parameters", "kind": "null_parameters"}])
    return cases


def validate_comparison(original, fixed):
    if original["metadata"]["metadata"] != fixed["metadata"]["metadata"]:
        raise ValueError("public metadata changed between original and fixed builds")
    declared = expected_cases(original["metadata"]["metadata"])
    if ([case["case"] for case in original["cases"]] != declared
            or [case["case"]["id"] for case in original["cases"]] != CASE_IDS
            or [case["case"]["id"] for case in fixed["cases"]] != CASE_IDS
            or [case["case"] for case in original["cases"]]
            != [case["case"] for case in fixed["cases"]]):
        raise ValueError("pinned original/fixed case declarations changed")
    for report in (original, fixed):
        for case in report["cases"]:
            case_id = case["case"]["id"]
            kind = (case_id if case_id.startswith("null_") else "valid"
                    if case_id == "defaults" or case_id.endswith(("/minimum", "/maximum")) else "invalid")
            if case["case"]["kind"] != kind or case.get("execution") != "completed":
                raise ValueError("pinned case kind or native execution changed")
            kinds = [kind, "valid"] if kind == "invalid" else [kind]
            if [call["kind"] for call in case["calls"]] != kinds:
                raise ValueError("pinned native call sequence changed")
            for call in case["calls"]:
                names = [item["check"] for item in call["checks"]]
                required = BASE_CHECKS | ({"error_message"} if call["kind"] == "invalid"
                                         and call["return_code"] == 2 else set())
                if len(names) != len(set(names)) or set(names) != required:
                    raise ValueError("pinned native check inventory changed")
    if [case["case"]["id"] for case in original["cases"] if not case["ok"]] != NAN_CASES:
        raise ValueError("original did not reproduce exactly the three NaN failures")
    if not fixed["summary"]["ok"] or any(not case["ok"] for case in fixed["cases"]):
        raise ValueError("fixed library failed its selected parameter contract")
    for before, after in zip(original["cases"], fixed["cases"]):
        if (not before["metadata_unchanged"] or not after["metadata_unchanged"]
                or before["recheck_policy"] != "same-instance"
                or after["recheck_policy"] != "same-instance"):
            raise ValueError("metadata preservation or same-instance policy changed")
        case_id = before["case"]["id"]
        if case_id not in NAN_CASES:
            if before["calls"] != after["calls"]:
                raise ValueError(f"unrelated native control changed: {case_id}")
            if any(failures(call) for call in before["calls"]):
                raise ValueError(f"unrelated native finding: {case_id}")
            continue
        if len(before["calls"]) != 2 or len(after["calls"]) != 2:
            raise ValueError("NaN case did not retain its valid recheck")
        invalid, corrected = before["calls"][0], after["calls"][0]
        if (invalid["kind"] != "invalid" or corrected["kind"] != "invalid"
                or invalid["return_code"] != 0 or corrected["return_code"] != 2
                or failures(invalid) != ["return_code"] or failures(corrected)
                or invalid["error_message"] is not None
                or invalid["diagnostic_channel"] is not None
                or invalid["error_pointer_present"] is not False
                or corrected["error_message"] != "Parameter out of range"
                or corrected["diagnostic_channel"] != "error"
                or corrected["error_pointer_present"] is not True
                or invalid["general_message"] is not None
                or corrected["general_message"] is not None
                or invalid["general_pointer_present"] is not False
                or corrected["general_pointer_present"] is not False
                or invalid["parameter_mutations"] or corrected["parameter_mutations"]):
            raise ValueError(f"NaN findings differ from the declared correction: {case_id}")
        first_checks = {item["check"] for item in invalid["checks"]}
        corrected_checks = {item["check"] for item in corrected["checks"]}
        if corrected_checks != first_checks | {"error_message"}:
            raise ValueError("NaN correction changed an unrelated check")
        retry_before, retry_after = before["calls"][1], after["calls"][1]
        # A successful return leaves the old error pointer inactive in the fixed DLL.
        if (retry_before["kind"] != "valid" or retry_before["return_code"] != 0
                or retry_before["error_pointer_present"] is not False
                or retry_after["error_pointer_present"] is not True
                or failures(retry_before) or failures(retry_after)):
            raise ValueError("NaN recovery or diagnostic-pointer retention changed")
        before_fields = {key: value for key, value in retry_before.items() if key != "error_pointer_present"}
        after_fields = {key: value for key, value in retry_after.items() if key != "error_pointer_present"}
        if before_fields != after_fields:
            raise ValueError("NaN valid recheck changed another semantic control")
    return {"metadata_identical": True, "case_declarations_identical": True,
            "unchanged_cases": 21, "corrected_nan_cases": NAN_CASES,
            "original_nan_findings": ["return_code"],
            "diagnostics": "only the return-associated channel is read"}


def check_native(output, source, label, expected_commit, compiler, abi_receipt):
    library, receipt = build(source, output / label, compiler, expected_commit)
    if (receipt["source_commit"] != expected_commit or len(receipt["sources"]) != 58
            or len(receipt["generated"]) != 18):
        raise ValueError(f"unexpected {label} source or generated-file inventory")
    report_path = output / f"{label}-report.json"
    execution = saved_run(output, f"{label}-checker", [
        "-m", "inverter_interface_checks", "--library", str(library),
        "--adapter", "openibr-1.1", "--output", str(report_path),
        "--build-receipt", str(output / label / "build.json"),
        "--abi-probe", str(abi_receipt)], 1 if label == "original" else 0, 90)
    return read_report(report_path), receipt, execution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--fixed", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cc", default=os.environ.get("CC", "clang"))
    parser.add_argument("--expected-system")
    parser.add_argument("--expected-machine")
    args = parser.parse_args()
    if struct.calcsize("P") != 8:
        parser.error("native checks require 64-bit Python")
    if args.expected_system and platform.system() != args.expected_system:
        parser.error("runner OS does not match the declared target")
    if args.expected_machine and platform.machine().lower() != args.expected_machine.lower():
        parser.error("process architecture does not match the declared target")
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("output directory already exists")
    output.mkdir(parents=True)
    executed = []
    try:
        executable_suffix = ".exe" if os.name == "nt" else ""
        library_suffix = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
        ordinary = output / "abi-ordinary.json"
        for label, options, expected in (("abi-ordinary", [], 0), ("abi-packed", ["--packed"], 1)):
            receipt_path = output / f"{label}.json"
            executed.append(saved_run(output, label, [
                "tools/probe_abi.py", "--cc", args.cc,
                "--output", str(output / (label + executable_suffix)),
                "--receipt", str(receipt_path), *options], expected))
            observed = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (observed["comparison"]["matches"] is not (expected == 0)
                    or observed["producer_library_attestation"] is not False):
                raise ValueError("header probe disagrees with its declared control or scope")
        for mode, expected in (("good", 0), ("instance-overrun", 1)):
            library = output / (mode + library_suffix)
            build_receipt = output / f"{mode}-build.json"
            report_path = output / f"{mode}-report.json"
            executed.append(saved_run(output, f"{mode}-build", [
                "tools/build_fixture.py", "--cc", args.cc, "--fixture", mode,
                "--output", str(library), "--receipt", str(build_receipt)]))
            executed.append(saved_run(output, f"{mode}-checker", [
                "-m", "inverter_interface_checks", "--library", str(library),
                "--abi-probe", str(ordinary), "--build-receipt", str(build_receipt),
                "--output", str(report_path)], expected))
            report = read_report(report_path)
            failed_checks = {name for case in report["cases"] for call in case.get("calls", [])
                             for name in failures(call)}
            if (report["summary"]["ok"] is not (expected == 0)
                    or failed_checks != (set() if mode == "good" else {"Instance/guards"})):
                raise ValueError("controlled fixture did not produce exactly its intended findings")
        refused = output / "packed-refused-report.json"
        executed.append(saved_run(output, "packed-probe-refused", [
            "-m", "inverter_interface_checks", "--library", str(output / ("good" + library_suffix)),
            "--abi-probe", str(output / "abi-packed.json"), "--output", str(refused)], 2))
        if refused.exists():
            raise ValueError("invalid ABI receipt unexpectedly produced a model report")
        # More compiler-backed tests need an enclosing budget; native worker limits stay unchanged.
        executed.append(saved_run(output, "fixtures", [
            "-m", "unittest", "discover", "-s", "tests", "-v"], timeout=600, compiler=args.cc))
        original, original_build, run = check_native(output, args.original, "original", ORIGINAL, args.cc, ordinary)
        executed.append(run)
        fixed, fixed_build, run = check_native(output, args.fixed, "fixed", FIXED, args.cc, ordinary)
        executed.append(run)
        if (set(original_build["sources"]) != set(fixed_build["sources"])
                or original_build["generated"] != fixed_build["generated"]
                or [name for name in original_build["sources"]
                    if original_build["sources"][name] != fixed_build["sources"][name]]
                != ["ieee_cigre_dll/gfm_battery_dll.c"]):
            raise ValueError("original/fixed comparison changed an unrelated build input")
        comparison = validate_comparison(original, fixed)
        summary = {"schema": "inverter-native-ci/2", "ok": True,
                   "scope": "host-header ABI, native loader, metadata and parameter validation",
                   "producer_library_attestation": False,
                   "host": {"os": platform.system(), "architecture": platform.machine(),
                            "python": platform.python_version()}, "executed": executed,
                   "original": original["summary"], "fixed": fixed["summary"],
                   "comparison": comparison}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        (output / "failure.json").write_text(json.dumps({"ok": False, "executed": executed,
                                                        "error": str(error)}, indent=2) + "\n",
                                             encoding="utf-8")
        parser.error(str(error))
    print("Native ABI/fixture controls and pinned OpenIBR original/fixed comparison passed.")


if __name__ == "__main__":
    main()
