#!/usr/bin/env python3
"""Build the public OpenIBR DLL sources in a separate, recorded tree."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inverter_interface_checks.cli import compiler_identity
from inverter_interface_checks.process import sha256

SCHEMAS = (
    ("companion_algorithms", "ac_checks_A"),
    ("companion_algorithms", "ac_monitor_A"),
    ("companion_algorithms", "current_source_A"),
    ("companion_algorithms", "power_limiter_A"),
    ("gfm_essentials", "current_limiting_A"),
    ("gfm_essentials", "machine_model_A"),
    ("design_specific_examples", "circuit_controls_B"),
)
SOURCES = (
    "ieee_cigre_dll/gfm_battery_dll.c", "ieee_cigre_dll/gfm_battery_app.c",
    "c_language_library/gfm_essentials/machine_model_A/machine_model_A.c",
    "c_language_library/gfm_essentials/current_limiting_A/current_limiting_A.c",
    "c_language_library/companion_algorithms/ac_monitor_A/ac_monitor_A.c",
    "c_language_library/companion_algorithms/ac_checks_A/ac_checks_A.c",
    "c_language_library/companion_algorithms/current_source_A/current_source_A.c",
    "c_language_library/companion_algorithms/power_limiter_A/power_limiter_A.c",
    "c_language_library/design_specific_examples/circuit_controls_B/circuit_controls_B.c",
    "c_language_library/helper_lib/cmplx.c", "c_language_library/helper_lib/timers.c",
)


def public_git(source, arguments):
    environment = dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", "-C", str(source), *arguments], capture_output=True,
                          timeout=15, check=True, env=environment).stdout


def build(source, output, compiler=None, commit=None):
    source = Path(source).resolve(strict=True)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("build output already exists")
    commit = public_git(source, ["rev-parse", "--verify", commit or "HEAD"]).decode().strip()
    names = public_git(source, ["ls-tree", "-r", "--name-only", "-z", commit]).decode().split("\0")
    tree = output / "source"
    tree.mkdir(parents=True)
    original_hashes = {}
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe source path")
        if (name.startswith(("c_language_library/", "ieee_cigre_dll/", "schema_tools/"))
                and path.suffix in (".c", ".h", ".py", ".yaml", ".txt")) or name in ("LICENSE", "NOTICE"):
            data = public_git(source, ["show", f"{commit}:{name}"])
            destination = tree / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            original_hashes[name] = hashlib.sha256(data).hexdigest()
    for name in ("IEEE_Cigre_DLLInterface.h", "IEEE_Cigre_DLLInterface_types.h"):
        if original_hashes[f"ieee_cigre_dll/{name}"] != sha256(ROOT / "third_party" / "openibr" / name):
            raise ValueError("public header differs from the declared adapter profile")
    commands = []
    log_path = output / "build.log"

    def run(arguments):
        commands.append([str(argument).replace(str(tree), "<source>").replace(str(output), "<build>")
                         for argument in arguments])
        with log_path.open("ab") as log:
            subprocess.run(list(map(str, arguments)), cwd=tree, stdout=log, stderr=log,
                           timeout=60, check=True)

    for group, module in SCHEMAS:
        base = tree / "c_language_library" / group
        run([sys.executable, "-I", "-B", tree / "schema_tools" / "generate_header.py",
             base / f"{module}_schema.yaml", base / module])
    for script in ("ieee_cigre_dll/logging/generate_signal_catalog.py",
                   "ieee_cigre_dll/logging/generate_extra_outputs.py",
                   "ieee_cigre_dll/generate_dll_config.py"):
        run([sys.executable, "-I", "-B", tree / script])
    executable = shutil.which(compiler or "clang")
    if not executable:
        raise ValueError("clang compiler not found")
    suffix = ".dll" if os.name == "nt" else ".dylib" if sys.platform == "darwin" else ".so"
    library = output / f"GFM_Battery_OpenIBR{suffix}"
    flags = ["-std=c99", "-Wall", "-Wextra", "-O2", "-DNDEBUG"]
    flags.append("-dynamiclib" if sys.platform == "darwin" else "-shared")
    if os.name != "nt" and sys.platform != "darwin":
        flags.append("-fPIC")
    command = [executable, *flags, "-o", library, *SOURCES]
    if os.name != "nt":
        command.append("-lm")
    run(command)
    changed = [name for name, digest in original_hashes.items() if sha256(tree / name) != digest]
    if changed:
        raise ValueError(f"tracked sources changed during build: {changed}")
    generated = {path.relative_to(tree).as_posix(): sha256(path)
                 for path in sorted(tree.rglob("*"))
                 if path.is_file() and path.relative_to(tree).as_posix() not in original_hashes}
    tool = compiler_identity(executable)
    tool["scope"] = "compiler invoked by this recorded build"
    receipt = {
        "schema": "inverter-openibr-build/1", "source_commit": commit,
        "scope": "production library build; no initialization or electrical stepping",
        "compiler": tool, "python": sys.version, "sources": original_hashes,
        "generator_dependency": {"PyYAML": importlib.metadata.version("PyYAML")},
        "generated": generated, "commands": commands,
        "library": {"name": library.name, "sha256": sha256(library)},
    }
    (output / "build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return library, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cc")
    parser.add_argument("--commit", help="read an immutable commit without changing the checkout")
    args = parser.parse_args()
    try:
        library, _ = build(args.source, args.output_dir, args.cc, args.commit)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(str(error))
    print(f"Built public OpenIBR library: {library}")


if __name__ == "__main__":
    main()
