#!/usr/bin/env python3
"""Compile only the bundled software fixture and retain its build identity."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inverter_interface_checks.cli import compiler_identity
from inverter_interface_checks.process import sha256

MODES = {
    "good": 0, "nan": 1, "bounds": 2, "return": 3, "message": 4,
    "parameter-write": 5, "input-write": 6, "overrun": 7, "stale-message": 8,
    "metadata": 9, "missing-export": 10, "crash": 11, "timeout": 12,
    "metadata-write": 13, "null-info": 14, "output-limit": 16,
    "state-write": 17, "string-write": 18,
    "state-padding": 19, "instance-padding": 20,
    "signed-char": 21, "unsigned-char": 22,
    "descendant": 23, "metadata-pointer": 24, "sample-time": 25,
    "metadata-nan": 26, "port-width": 27, "duplicate-name": 28,
    "interface-version": 29, "text-encoding": 30,
    "fast-output": 31,
    "warning": 32, "warning-message": 33, "instance-overrun": 34,
    "inactive-error": 35, "inactive-general": 36, "inactive-unknown": 37,
    "identifier": 38, "fixed-value": 39, "normalization": 40,
    "parameter-padding": 41, "parameter-pointer": 42, "retry-error": 43,
    "normalization-bounds": 44, "normalization-nan": 45, "normalization-inf": 46,
}


def compile_fixture(output, mode="good", compiler=None, layout=False):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("output already exists")
    executable = compiler or ("clang" if os.name == "nt" else "cc")
    resolved = shutil.which(executable)
    if not resolved:
        raise ValueError(f"compiler not found: {executable}")
    source = ROOT / "tests" / "fixtures" / "contract_model.c"
    header = ROOT / "third_party" / "openibr" / "IEEE_Cigre_DLLInterface.h"
    types = header.with_name("IEEE_Cigre_DLLInterface_types.h")
    sources = {path.relative_to(ROOT).as_posix(): sha256(path) for path in (source, header, types)}
    command = [resolved, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2",
               f"-DFIXTURE_MODE={MODES[mode]}", "-I", str(header.parent)]
    if mode == "unsigned-char":
        command.append("-funsigned-char")
    elif mode == "signed-char":
        command.append("-fsigned-char")
    if layout:
        command.append("-DPRINT_LAYOUT")
    elif sys.platform == "darwin":
        command.append("-dynamiclib")
    else:
        command.append("-shared")
        if os.name != "nt":
            command.append("-fPIC")
    command += [str(source), "-o", str(output)]
    if os.name != "nt":
        command.append("-lm")
    result = subprocess.run(command, capture_output=True, timeout=90)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace"))
    if sources != {path.relative_to(ROOT).as_posix(): sha256(path) for path in (source, header, types)}:
        raise ValueError("source changed during compilation")
    return {
        "schema": "inverter-fixture-build/1", "scope": "software fixture",
        "fixture": mode, "compiler": compiler_identity(resolved), "sources": sources,
        "flags": [argument for argument in command[1:] if argument.startswith("-")],
        "host": {"os": platform.system(), "architecture": platform.machine()},
        "library": {"name": output.name, "sha256": sha256(output)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--fixture", choices=MODES, default="good")
    parser.add_argument("--cc", default=None)
    args = parser.parse_args()
    if args.receipt and args.receipt.exists():
        parser.error("receipt already exists")
    try:
        receipt = compile_fixture(args.output, args.fixture, args.cc)
        if args.receipt:
            with args.receipt.open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, indent=2)
                stream.write("\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(f"Built software fixture: {args.output.name}")


if __name__ == "__main__":
    main()
