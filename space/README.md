---
title: Inverter interface reports
colorFrom: green
colorTo: gray
sdk: static
app_file: index.html
license: apache-2.0
short_description: OpenIBR parameter reports, explored in your browser
tags:
  - energy
  - power-systems
  - openibr
  - inverters
pinned: false
---

# Inverter interface reports

Explore the retained OpenIBR parameter checks from
[inverter-interface-checks v0.2.3](https://github.com/wattness/inverter-interface-checks/releases/tag/v0.2.3),
or open a locally generated report. The Space reads reports in the browser;
the native checker runs on your machine.

## Recorded comparison

The six original and corrected report files are unchanged copies of the
[retained three-platform native run](https://github.com/wattness/inverter-interface-checks/actions/runs/41331699131).
The original source is HeronPower/OpenIBR commit
[5e2396c](https://github.com/HeronPower/OpenIBR/commit/5e2396cef8e57765c6a8fefe34fc379c3a60c163).
The proposed correction is Wattness/OpenIBR commit
[0489b0f](https://github.com/wattness/OpenIBR/commit/0489b0f2c5cea392f6b6b0743dae43a630732e58),
submitted as [upstream PR #14](https://github.com/HeronPower/OpenIBR/pull/14).

Each platform has 24 cases. The original validator accepts NaN for H, D and
kDroop; the proposed correction rejects those three inputs. The other 21
case objects match after removing only each case's elapsed_seconds field.
Model metadata, adapter and policy match. The viewer compares these fields
before showing the release summary and preserves JSON numerical spelling.
The checker records metadata and parameter validation only; it never
initializes or steps the electrical model.

manifest.json pins each report's size, SHA-256 and library identity, both
source commits and the released wheel. The page hashes the downloaded samples
before parsing them. A mismatch produces no comparison. The download buttons
return the original bytes. The validation summary and wheel also retain their
published release digests. These hashes identify the recorded artifacts;
they are not an independent producer-library ABI attestation.

## Your report

Choose a JSON file, or paste the complete output from the local checker.
Only inverter-interface-report/2 is supported. Version 1 is refused rather
than reinterpreted. The native report schema is unchanged.

The reader checks the file's structure, typed returns, diagnostic channels,
case/recheck sequence, completeness and summary counts. A positive outcome is
labelled **Reported pass**: the native observations are supplied by the file's
producer and are not independently rerun or authenticated by this page.
Failed native calls, missing exports and incomplete suites remain visible.

Reports and pasted text remain in the tab. The application has no upload
endpoint, telemetry, cookies, local storage or third-party script/font requests.
Only its static assets are fetched. Report text is rendered as text, never HTML.
A file larger than 2 MB is refused before it is read. The worker also limits
JSON to 64 object/array levels, 50,000 values, 8,192 UTF-16 code units per string
and 256 cases. Duplicate keys, nonfinite JSON numbers and invalid UTF-8 are
refused. The worker stops after five seconds; replacing or clearing a report
cancels its earlier reader. Numeric text retains signed zero, tiny boundary
values, long decimal spellings and integers beyond JavaScript's safe range.

These reader limits are separately versioned browser behavior. They do not
change the Python checker's adapter, report or native-validation contracts.

## Run locally

Use Python 3.12 in a virtual environment. Download the released wheel from the
Run locally tab, or install it from its pinned GitHub release URL. The page
provides commands for Windows and macOS/Linux. Supply your own trusted compiled
OpenIBR library, select the openibr-1.1 adapter and choose a new output filename.
Open that report in this Space.

The checker uses Python's standard library at runtime. Native process isolation
contains ordinary crashes, not arbitrary code. Execute libraries whose code and
provenance you trust. See the
[checker contract](https://github.com/wattness/inverter-interface-checks#checks)
for supported policies, host-layout evidence and interpretation limits.

## Source and checks

The Space source is maintained in
[the checker's space directory](https://github.com/wattness/inverter-interface-checks/tree/main/space).

- index.html, style.css and app.mjs provide the interface.
- report-worker.mjs and report-core.mjs parse and describe reports.
- reports/ preserves six native reports and the released validation summary.
- downloads/ preserves the released Python wheel.
- manifest.json records the artifact and source pins.
- verify_assets.py checks byte identities and compares the original controls
  independently, without loading a native library.
- tests/ covers the parser and real browser behavior: local file handling,
  downloads, negative evidence, keyboard navigation, desktop/mobile layouts,
  text injection and absence of outbound report data.

```sh
python3 verify_assets.py
npm ci --ignore-scripts
npx playwright install chromium
npm test
```

The browser test server serves only allow-listed app assets on a loopback port
and closes after the checks. The production Space is static.

## License and scope

Apache-2.0; see LICENSE and third-party/OpenIBR-NOTICE. Original OpenIBR notices
and provenance are preserved. Wattness wrote the viewer and checker; the
reported model metadata comes from the pinned OpenIBR builds. This tool is
independent of Heron Power, IEEE and CIGRE and implies no endorsement or
certification. A passing interface report does not establish electrical
suitability, CIGRE TB958 conformance, model memory safety or simulator compatibility.
