# inverter-interface-checks

Check a compiled inverter interface's metadata and parameter validator without
initializing or stepping its electrical model. The CLI uses Python's standard
library. A compiler is needed only for the bundled software fixtures.

The initial adapters implement the native 64-bit cdecl layout exposed by
OpenIBR's public IEEE/CIGRE 1.1 header. They do not establish CIGRE TB958
conformance, electrical suitability or simulator compatibility.

## Run

Use Python 3.10 or later from this checkout:

```sh
python -m inverter_interface_checks --library ./model.so --output report.json
python -m inverter_interface_checks --library ./GFM_Battery_OpenIBR.dll --adapter openibr-1.1
```

Use `.dylib` on macOS and `.dll` on Windows. Supply an absolute path or a path
relative to the current directory. Exit codes are 0 for complete passing checks,
1 for a failed or incomplete check, and 2 for an invalid invocation. JSON reports
are written only to new files; `--format json` also emits JSON on stdout.

The report records the loaded library hash, adapter and checker source hashes,
native structure sizes/offsets, metadata, case inputs, returns, messages and
individual findings. `--source file.c` records explicitly supplied file hashes;
it does not establish their correspondence to the library. `--compiler clang`
records a local tool probe, not proof of the library's build compiler.
`--build-receipt build.json` attaches a supplied build record only after its
library hash matches. This is not an independent build attestation.

## Checks

- All eight public `Model_*` exports exist; only `Model_GetInfo` and
  `Model_CheckParameters` are called.
- Version, sample time, mode, counts, port widths, names, types and parameter
  defaults/bounds are valid under the declared profile.
- Editable numeric parameters accept inclusive bounds and reject adjacent
  representable values outside them. Floating parameters also reject NaN and
  both infinities.
- Return codes and required messages match the adapter. A valid recheck runs
  after each invalid probe on the same host instance.
- Parameter, input/output and state buffers, string pointees, guard bytes,
  alignment padding and Instance bytes remain unchanged, apart from the two
  message pointers. Metadata remains unchanged.
- Missing exports, malformed metadata, native crashes, timeouts and excessive
  native output produce failed results. Incomplete suites cannot pass.

Each independent case uses a fresh process and library load. Rechecks share that
case's Instance. The default limits are 2 seconds per worker, 60 seconds for the
suite and 256 cases. Metadata is limited to 256 rows per category, 256 scalars per
port, 65,536 states per scalar type and 4,096 bytes per text field. Native text
must be NUL-terminated UTF-8; other encodings are unsupported. Native output is
rejected at 128 KiB, including after worker completion. Unix also applies a
hard file-size limit; Windows polling can overshoot the rejection threshold
before stopping the worker. Retained report excerpts are limited to 8 KiB.

Process isolation protects the calling Python host from ordinary native crashes.
It is not a security sandbox: approved libraries can still access files and
network resources. The worker receives a minimal environment. On Unix the
process group is stopped after completion as well as on limit failures. On
Windows this version stops the worker process; it does not claim descendant
process containment. Only execute libraries whose code and provenance you trust.

## Adapter contract

`--adapter` accepts a bundled name or an explicit JSON file. The ABI, calling
convention, native field order, inclusive bounds, allowed returns and message
policies are declared in
[`inverter_interface_checks/adapters/ieee-cigre-1.1.json`](inverter_interface_checks/adapters/ieee-cigre-1.1.json).
Unknown adapter fields and unsupported layouts are rejected.

Host port and parameter structures use one typed field per metadata row, in
declared order, with each port's Width and native alignment. No OpenIBR private
wrapper structure is imported. The OpenIBR adapter additionally requires the
model name and ordered H, D and kDroop `real64_T` parameters.

These adapters require `Model_CheckParameters` to be callable without lifecycle
setup. Validators requiring `Model_FirstCall` or initialization need a separate
adapter design. Initialization, outputs, iteration and termination are not
executed. Fixed parameters and string parameters receive default validation and
buffer checks; their edit/range semantics are excluded explicitly. Native
`char_T` parameter signedness must be declared as `signed` or `unsigned` in a
custom adapter; the bundled adapters reject such parameters rather than infer
target compiler behavior. A successful call is not required to clear an older
error message unless `clear_error_on_success` is enabled. The OpenIBR adapter
allows its observed null-parameter rejection without an error message.

## Software fixtures and tests

The C fixtures are independently written software tests, not electrical models.
They mix float32, float64, integer, string and vector fields, plus deliberate
validation, buffer, metadata, crash and timeout defects.

```sh
mkdir build
python tools/build_fixture.py --output build/good.so --receipt build/good-build.json
python -m inverter_interface_checks --library build/good.so --build-receipt build/good-build.json
python -m unittest discover -s tests -v
```

Use the platform's library suffix. `--cc clang` selects a compiler; tests also
accept `CC`. Windows fixture builds use native x64 clang with an MSVC developer
environment. CI executes the same tests on Ubuntu, macOS and Windows and builds
the pinned public original and corrected OpenIBR libraries for adapter checks.
Its OpenIBR header generators alone require the pinned PyYAML CI dependency.
The original validator is an expected negative control, not a passing verdict.

## License

Apache-2.0. Public OpenIBR interface headers are retained unmodified, with their
original notices and source identities in [third_party/NOTICE.md](third_party/NOTICE.md).
This tool is independent of Heron Power, IEEE and CIGRE; it implies no endorsement.
