#!/usr/bin/env python3
"""Build/run only the bundled C header-layout probe, retaining its exact inputs.

This executable contains no controller/model entry points. Its result compares
the copied host headers to Python ctypes; it does not attest a producer library.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inverter_interface_checks.abi import compare_native_probe


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compile_probe(output, compiler=None, packed=False, extra_flags=()):
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("probe output already exists")
    if not output.parent.is_dir():
        raise ValueError("probe output directory must already exist")
    resolved = shutil.which(compiler or ("clang" if os.name == "nt" else "cc"))
    if not resolved:
        raise ValueError("native C compiler not found")
    source = ROOT / "tests" / "fixtures" / "abi_probe.c"
    header = ROOT / "third_party" / "openibr" / "IEEE_Cigre_DLLInterface.h"
    types = header.with_name("IEEE_Cigre_DLLInterface_types.h")
    sources = {path.relative_to(ROOT).as_posix(): sha256(path) for path in (source, header, types)}
    driver = Path(resolved).stem.lower()
    if driver in ("cl", "clang-cl"):
        flags = ["/nologo", "/TC", "/W4", "/Od", "/I" + str(header.parent)]
        flags += ["/clang:-std=c99"] if driver == "clang-cl" else ["/std:c11"]
        flags += ["/Zp1"] if packed else []
        flags += list(extra_flags)
        command = [resolved, *flags, str(source), "/Fe:" + str(output),
                   "/Fo:" + str(output.with_suffix(".obj"))]
        version_command = [resolved, "--version"] if driver == "clang-cl" else [resolved, "/Bv"]
    else:
        flags = ["-std=c99", "-Wall", "-Wextra", "-O0", "-I", str(header.parent)]
        flags += ["-fpack-struct=1"] if packed else []
        flags += list(extra_flags)
        command = [resolved, *flags, str(source), "-o", str(output)]
        version_command = [resolved, "--version"]
    version = subprocess.run(version_command, capture_output=True, timeout=30)
    compiled = subprocess.run(command, capture_output=True, timeout=90, cwd=output.parent)
    if compiled.returncode:
        raise ValueError("native probe compilation failed: " +
                         compiled.stderr.decode("utf-8", errors="replace")[:8192])
    after = {path.relative_to(ROOT).as_posix(): sha256(path) for path in (source, header, types)}
    if sources != after:
        raise ValueError("probe sources changed during compilation")
    return {
        "schema": "inverter-native-abi-probe-build/1",
        "scope": "host-header-software-probe", "producer_library_attestation": False,
        "compiler": {"executable": str(Path(resolved).resolve()), "sha256": sha256(resolved),
                     "version": (version.stdout + version.stderr).decode("utf-8", errors="replace")[:8192],
                     "version_exit_code": version.returncode},
        "command": command, "flags": flags, "sources": sources,
        "compiler_identity_timeout_seconds": 30,
        "compile_timeout_seconds": 90,
        "host": {"os": platform.system(), "architecture": platform.machine(),
                 "python": platform.python_version()},
        "packing": "one-byte-negative-fixture" if packed else "compiler-default",
        "executable": {"name": output.name, "sha256": sha256(output)},
        "compiler_output": (compiled.stdout + compiled.stderr).decode("utf-8", errors="replace")[:8192],
    }


def run_probe(output, receipt, char_signedness="unsupported"):
    output = Path(output).resolve()
    if receipt.get("executable", {}).get("sha256") != sha256(output):
        raise ValueError("native probe executable identity changed before execution")
    result = subprocess.run([str(output)], capture_output=True, timeout=5, cwd=output.parent)
    if result.returncode:
        raise ValueError(f"native probe exited with {result.returncode}")
    if len(result.stdout) > 131072 or len(result.stderr) > 8192:
        raise ValueError("native probe output exceeds cap")
    if receipt["executable"]["sha256"] != sha256(output):
        raise ValueError("native probe executable identity changed during execution")
    observation = json.loads(result.stdout)
    compatibility = compare_native_probe(observation, char_signedness)
    return {**receipt, "observation": observation, "comparison": compatibility,
            "probe_timeout_seconds": 5, "probe_exit_code": result.returncode,
            "probe_stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "probe_stderr": result.stderr.decode("utf-8", errors="replace")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--cc")
    parser.add_argument("--packed", action="store_true", help="compile deliberately packed negative fixture")
    parser.add_argument("--flag", action="append", default=[], help="additional recorded compiler flag")
    parser.add_argument("--char-signedness", choices=("unsupported", "signed", "unsigned"),
                        default="unsupported")
    args = parser.parse_args()
    if args.receipt.exists():
        parser.error("receipt already exists")
    try:
        receipt = compile_probe(args.output, args.cc, args.packed, args.flag)
        observed = run_probe(args.output, receipt, args.char_signedness)
        with args.receipt.open("x", encoding="utf-8") as stream:
            json.dump(observed, stream, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(json.dumps({"matches": observed["comparison"]["matches"],
                      "receipt": str(args.receipt), "producer_library_attestation": False}))
    return 0 if observed["comparison"]["matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
