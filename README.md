# inverter-interface-checks

Check a compiled inverter interface's metadata and parameter validator without
initializing or stepping its electrical model. The CLI uses Python's standard
library. A compiler is needed only for the bundled software fixtures and native
header-layout probe.

The adapters implement the native 64-bit cdecl layout exposed by OpenIBR's
public IEEE/CIGRE 1.1 header. Passing a selected adapter does not establish CIGRE
TB958 conformance, electrical suitability or simulator compatibility. This
version is `0.2.0`; the original `v0.1.0` release and its reports remain separate.

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

Reports use `inverter-interface-report/2`. They record the library hash, adapter
hash and resolved policies, checker source hashes, declared native layouts,
metadata, case inputs, returns, active-channel messages and individual findings.
Consumers of report version 1 must explicitly handle the new schema. Raw
`FixedValue` metadata is retained as `fixed_value`, alongside the `fixed` boolean;
neither field establishes whether a controller applies parameter changes while
running.

`--source file.c` records explicitly supplied file hashes; it does not establish
their correspondence to the library. `--compiler clang` records a local tool
probe, not proof of the library's build compiler. `--build-receipt build.json`
attaches a supplied build record only after its library hash matches. These are
supplied records, not independent build attestations.

## Checks

- All eight public `Model_*` exports exist; only `Model_GetInfo` and
  `Model_CheckParameters` are called.
- Version, sample time, mode, counts, port widths, names, types and parameter
  defaults/bounds are valid under the declared profile.
- Editable numeric parameters are tested against the selected bounds and
  nonfinite policies. Excluded probes are recorded in `skipped`.
- Return codes and required messages match the adapter. A same-instance valid
  recheck after rejection runs only when the adapter selects it.
- Parameter, input/output and state buffers, caller-owned string pointees,
  padding, Instance bytes and surrounding guard bytes are checked. Only the two
  diagnostic pointers are exempt from the Instance byte comparison. Metadata
  must remain unchanged.
- Under `allow-normalization`, accepted status 0/1 calls may change numeric
  parameter field bytes. Changes retain before/after hex records and the resulting
  values must still satisfy the selected bounds and nonfinite policies. String
  pointers/pointees, parameter padding, I/O, state, Instance and guards remain
  protected. Status 2 does not permit numeric normalization.
- Missing exports, malformed metadata, native crashes, timeouts and excessive
  native output produce failed results. Incomplete suites cannot pass.

Diagnostic dispatch follows the actual return code, even when it differs from
the expected code. Status 1 reads only `LastGeneralMessage`; status 2 reads only
`LastErrorMessage`. Status 0 and unknown statuses read neither. Neither pointer
is read when the call receives a null Instance. The report records the active
`diagnostic_channel` and pointer presence; an inactive pointer's presence is not
evidence that its pointee is readable. If `clear_error_on_success` is enabled,
success checks pointer presence without dereferencing stale error text.

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

Canaries detect changes to their own bytes. They do not detect every out-of-bounds
read, restored write or arbitrary write elsewhere. No-access guard pages and
source instrumentation are outside this checker version. A passing report is
not proof of native memory safety.

## Adapter contract

`--adapter` accepts a bundled name or an explicit JSON file. The ABI, calling
convention, native field order, allowed returns and message policies are declared
in [`inverter_interface_checks/adapters/ieee-cigre-1.1.json`](inverter_interface_checks/adapters/ieee-cigre-1.1.json).
Unknown fields and unsupported layouts are rejected. Integer return declarations
must be JSON integers; booleans and floating-point lookalikes are invalid.

These are checker/model policies, not universal standards obligations:

| Policy | Values | Compatibility default for an omitted optional field |
|---|---|---|
| `recheck_policy` | `same-instance`, `none` | `same-instance` |
| `parameter_mutation` | `forbid`, `allow-normalization` | `forbid` |
| `nonfinite` | `reject`, `skip` | `reject` |
| `name_syntax` | `nonempty`, `c-identifier-ascii` | `nonempty` |
| `fixed_value_policy` | `nonzero`, `zero-or-one` | `nonzero` |
| `bounds` | `inclusive`, `skip` | Required existing field |

The bundled adapters explicitly select inclusive bounds, nonfinite rejection,
same-instance rechecks, forbidden parameter mutation and nonzero fixed flags.
The generic adapter selects ASCII identifier syntax. OpenIBR selects nonempty
names because its pinned generated output labels contain member paths and array
indices, such as `circuitControls_OUT.v_bridge[0]`. The copied header does not
require C identifier syntax for these labels. `zero-or-one` rejects raw fixed flags other than 0 or 1;
`nonzero` treats any nonzero flag as fixed and preserves its integer value.

`skip` excludes the corresponding validator probes; it does not relax metadata
sanity checks. Numeric metadata must still have finite defaults/minima/maxima
and an in-range default. Policies compose: for example, `nonfinite: skip` does
not allow a normalized NaN to satisfy `bounds: inclusive`.

Host port and parameter structures use one typed field per metadata row, in
declared order, with each port's Width and native alignment. No OpenIBR private
wrapper structure is imported. The OpenIBR adapter additionally requires the
model name and ordered H, D and kDroop `real64_T` parameters.

These adapters require `Model_CheckParameters` to be callable without lifecycle
setup. Validators requiring `Model_FirstCall` or initialization need a separate
adapter design. FirstCall, PrintInfo, initialization, outputs, iteration and
termination are not executed. Fixed parameters and string parameters receive
default validation and buffer checks; their edit/range semantics are excluded
explicitly. Native `char_T` parameter signedness must be declared as `signed` or
`unsigned` in a custom adapter; the bundled adapters reject such parameters
rather than infer target compiler behavior. A successful call is not required
to clear an older error pointer unless `clear_error_on_success` is enabled. The
OpenIBR adapter allows its observed null-parameter rejection without an error
message.

## Native header-layout evidence

The bundled C probe contains no model entry points. It compares the copied host
headers with Python ctypes for scalar widths/alignment/signedness, endian and
floating representation, the six ABI aggregates/unions and mixed port/parameter
structures. Each aggregate comparison includes field offsets, widths and
alignment. Enum representation is recorded: OpenIBR declares ABI DataType fields
and integer function returns as `int`, so shrinking its unused enum typedefs
does not shrink those fields.

```sh
mkdir build
python tools/probe_abi.py --cc clang --output build/abi-probe --receipt build/abi-probe.json
python -m inverter_interface_checks --library ./model.so --abi-probe build/abi-probe.json --output report.json
```

Use an `.exe` probe executable on Windows. The receipt preserves compiler,
flags, exact probe/header hashes, host identity and native observations.
`--abi-probe` requires an integer zero probe exit, complete enum observations,
and checks the receipt schema/scope/size, pinned probe/header identities and
OS/process architecture, then recomputes the layout comparison before loading the
target library. These identities work from an installed wheel as well as the
checkout; the compiler tool itself requires the checkout. It does not compile or execute the supplied receipt's executable.
Without a receipt the report labels the layouts as ctypes declarations only;
with a matching receipt it labels them as a supplied host-header probe. In both
cases the producer library ABI remains unverified. A producer-specific build
probe or shim would need separate evidence.

`tools/probe_abi.py --packed` builds a deliberately packed negative probe and
returns 1 when the comparison rejects it. This is an expected control result,
not an ordinary compatible probe. It can preserve some structure sizes while
changing alignment; comparing only total sizes would miss that defect.

## Software fixtures and tests

The C fixtures are independently written software tests, not electrical models.
They mix float32, float64, integer, string and vector fields, plus deliberate
validation, diagnostic, buffer, metadata, crash and timeout defects.

```sh
mkdir build
python tools/build_fixture.py --output build/good.so --receipt build/good-build.json
python -m inverter_interface_checks --library build/good.so --build-receipt build/good-build.json
python -m unittest discover -s tests -v
```

Use the platform's library suffix. `--cc clang` selects a compiler; tests also
accept `CC`. Windows fixture builds use native x64 clang with an MSVC developer
environment. The public [native workflow](.github/workflows/native.yml) runs
controlled fixtures, complete header probes and the pinned original/fixed
OpenIBR parameter comparison on Linux x64, macOS ARM64 and Windows x64.
It retains ordinary/packed probe receipts, fixture reports, source/build hashes,
logs and exact native controls. A platform is verified only after its native job
executes successfully. The original validator must retain exactly its three NaN
failures; all 21 other cases and metadata remain identical. No lifecycle or
electrical hook is called.

## Report migration from 0.1

Version 0.2 writes `inverter-interface-report/2`; consumers should dispatch on
that schema instead of assuming version 1 semantics. Adapter optional fields
retain compatible defaults, while bundled adapters state their policies explicitly.

- Metadata adds raw `fixed_value`; compare it as well as the derived boolean.
- Calls record `diagnostic_channel`, pointer presence and numeric mutation bits.
  Inactive message text is unobserved, not an observed null diagnostic.
- Layout measurements include field widths and alignment. A supplied host-header
  probe is labelled separately from ctypes declarations and does not attest the
  producer library build.
- Instance guards add findings and legitimately change check totals. An invalid
  call returning 0 has a return-code failure; no error pointee is read or required
  for that actual return. Expected original OpenIBR NaN findings therefore change
  from two findings per case to one, preserving the same three failed cases.

The CLI exit meanings and exclusive-create JSON output remain unchanged. Reports
and evidence from version 0.1 must retain their original schema and interpretation.

## License

Apache-2.0. Public OpenIBR interface headers are retained unmodified, with their
original notices and source identities in [third_party/NOTICE.md](third_party/NOTICE.md).
This tool is independent of Heron Power, IEEE and CIGRE; it implies no endorsement.
