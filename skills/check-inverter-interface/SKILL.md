---
name: check-inverter-interface
description: Run bounded metadata and parameter checks for an explicitly supplied native inverter library.
---

Use only the library and source files supplied for this task. Choose a declared
adapter; do not infer a private C layout from pointer arithmetic.

1. Record the library's provenance and expected interface profile.
2. Run `python -m inverter_interface_checks --library PATH --adapter ADAPTER
   --output NEW_REPORT.json` from the checkout. State worker and total limits
   before extending them; incomplete results must remain failed.
3. Read the JSON findings and summarize exact failures, platform and identities.
   Separate explicit file hashes and supplied build records from verified build
   correspondence.
4. Treat software fixture results as software evidence. Make no electrical,
   numerical-readiness, simulator or cross-platform claim without its own run.

Do not call Model_Initialize, Model_Outputs or Model_Iterate. Do not fetch or
execute an unspecified library, install a simulator, post findings externally or
alter the user's machine configuration. Native process isolation is not a
security sandbox; only run approved code.
