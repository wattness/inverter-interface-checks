"""Command-line orchestration; native calls stay in bounded workers."""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

from . import __version__
from .contracts import load_adapter, plan_cases
from .process import run_worker, sha256


def compiler_identity(executable):
    resolved = shutil.which(executable)
    if not resolved:
        raise ValueError(f"compiler not found: {executable}")
    completed = subprocess.run([resolved, "--version"], capture_output=True,
                               timeout=5, check=True)
    return {"name": Path(resolved).name, "sha256": sha256(resolved),
            "version": completed.stdout[:4096].decode("utf-8", errors="replace"),
            "scope": "local tool probe; does not establish the library's build compiler"}


def positive_float(value):
    result = float(value)
    if not 0 < result <= 300:
        raise argparse.ArgumentTypeError("must be positive and at most 300 seconds")
    return result


def case_limit(value):
    result = int(value)
    if not 1 <= result <= 1024:
        raise argparse.ArgumentTypeError("must be between 1 and 1024")
    return result


def parser():
    result = argparse.ArgumentParser(description="Check native interface metadata and parameter contracts.")
    result.add_argument("--library", required=True, type=Path)
    result.add_argument("--adapter", default="ieee-cigre-1.1",
                        help="ieee-cigre-1.1, openibr-1.1, or an adapter JSON file")
    result.add_argument("--timeout", type=positive_float, default=2.0,
                        help="seconds per worker (default: 2)")
    result.add_argument("--total-timeout", type=positive_float, default=60.0,
                        help="seconds for metadata and all cases (default: 60)")
    result.add_argument("--max-cases", type=case_limit, default=256)
    result.add_argument("--source", type=Path, action="append", default=[],
                        help="hash an explicitly supplied source file; repeatable")
    result.add_argument("--compiler", help="record the local compiler's version and executable hash")
    result.add_argument("--build-receipt", type=Path,
                        help="attach a fixture build receipt matching the library hash")
    result.add_argument("--format", choices=("text", "json"), default="text")
    result.add_argument("--output", type=Path, help="write JSON to a new file")
    result.add_argument("--version", action="version", version=__version__)
    return result


def inspect(args):
    library = args.library.resolve(strict=True)
    if not library.is_file():
        raise ValueError("library must be a file")
    adapter, adapter_path, adapter_data = load_adapter(args.adapter)
    library_hash = sha256(library)
    identity = {
        "library": {"name": library.name, "sha256": library_hash},
        "adapter": {"id": adapter["id"], "name": adapter_path.name,
                    "sha256": hashlib.sha256(adapter_data).hexdigest()},
        "sources": [{"name": source.name, "sha256": sha256(source)} for source in args.source],
        "source_scope": "explicitly supplied files; source-to-library correspondence is unverified",
        "host": {"os": platform.system(), "architecture": platform.machine(),
                 "python": platform.python_version()},
        "engine": {"version": __version__, "files": {
            path.name: sha256(path) for path in sorted(Path(__file__).parent.glob("*.py"))
        }},
    }
    if args.compiler:
        identity["compiler_probe"] = compiler_identity(args.compiler)
    if args.build_receipt:
        data = args.build_receipt.read_bytes()
        if len(data) > 131072:
            raise ValueError("build receipt exceeds 128 KiB")
        receipt = json.loads(data)
        if (not isinstance(receipt, dict) or receipt.get("schema") not in (
                "inverter-fixture-build/1", "inverter-openibr-build/1")
                or not isinstance(receipt.get("library"), dict)
                or receipt["library"].get("sha256") != library_hash):
            raise ValueError("build receipt does not match the library")
        identity["build_receipt"] = receipt
        identity["build_receipt_sha256"] = sha256(args.build_receipt)
        identity["build_receipt_scope"] = "supplied record with matching library hash; not independent attestation"
    request = {"library": str(library), "library_sha256": library_hash, "adapter": adapter,
               "timeout": args.timeout, "action": "metadata"}
    started = time.monotonic()
    metadata = run_worker(request, min(args.timeout, args.total_timeout))
    report = {"schema": "inverter-interface-report/1", "identity": identity,
              "scope": "metadata and parameter validation; no initialization or electrical stepping",
              "limits": {"worker_seconds": args.timeout, "total_seconds": args.total_timeout,
                         "max_cases": args.max_cases, "worker_log_bytes": 131072},
              "metadata": metadata, "cases": [], "skipped": [], "unexecuted_case_ids": []}
    if metadata["ok"]:
        cases, report["skipped"] = plan_cases(metadata["metadata"])
        if len(cases) > args.max_cases:
            report["unexecuted_case_ids"] = [case["id"] for case in cases]
            report["incomplete_reason"] = "case_limit"
        else:
            request.update(action="case", metadata=metadata["metadata"])
            for index, case in enumerate(cases):
                remaining = args.total_timeout - (time.monotonic() - started)
                if remaining <= 0:
                    report["unexecuted_case_ids"] = [item["id"] for item in cases[index:]]
                    report["incomplete_reason"] = "total_timeout"
                    break
                request["case"] = case
                result = run_worker(request, min(args.timeout, remaining))
                report["cases"].append({"case": case, **result})
    complete = metadata["ok"] and not report["unexecuted_case_ids"]
    failed = sum(not item["ok"] for item in report["cases"])
    checks = [check for item in report["cases"] for call in item.get("calls", [])
              for check in call["checks"]]
    report["summary"] = {
        "ok": complete and failed == 0, "complete": complete,
        "cases_executed": len(report["cases"]), "cases_failed": failed,
        "checks_executed": len(checks), "checks_failed": sum(not check["ok"] for check in checks),
        "elapsed_seconds": round(time.monotonic() - started, 4),
    }
    return report


def render_text(report):
    summary = report["summary"]
    outcome = "PASS" if summary["ok"] else "FAIL"
    identity = report["identity"]
    lines = [f"{outcome}: {identity['library']['name']} ({identity['adapter']['id']})",
             f"{summary['cases_executed']} cases, {summary['cases_failed']} failed; "
             f"{summary['checks_executed']} checks, {summary['checks_failed']} failed"]
    if not report["metadata"]["ok"]:
        metadata = report["metadata"]
        detail = metadata.get("detail", metadata["execution"])
        lines.append(f"metadata: {detail}")
        if metadata.get("missing_exports"):
            lines.append("missing exports: " + ", ".join(metadata["missing_exports"]))
    for item in report["cases"]:
        if item["ok"]:
            continue
        failed = [check["check"] for call in item.get("calls", [])
                  for check in call["checks"] if not check["ok"]]
        if item.get("metadata_unchanged") is False:
            failed.append("metadata_unchanged")
        detail = ", ".join(sorted(set(failed))) or item.get("detail", item["execution"])
        lines.append(f"{item['case']['id']}: {detail}")
    if report["unexecuted_case_ids"]:
        lines.append(f"incomplete: {report['incomplete_reason']}; "
                     f"{len(report['unexecuted_case_ids'])} cases not executed")
    if report["skipped"]:
        lines.append(f"{len(report['skipped'])} exclusions recorded in JSON")
    lines.append("Scope: metadata and parameters. Electrical behavior is untested.")
    return "\n".join(lines)


def main(argv=None):
    command = parser()
    args = command.parse_args(argv)
    if args.output and args.output.exists():
        command.error("output already exists; choose a new file")
    try:
        report = inspect(args)
        encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        command.error(str(error))
    print(encoded, end="") if args.format == "json" else print(render_text(report))
    return 0 if report["summary"]["ok"] else 1
