---
name: check-inverter-interface
description: Run bounded metadata and parameter checks for an explicitly supplied native inverter library.
---

Use only the library and source files supplied for this task. Choose a declared
adapter; do not infer a private C layout from pointer arithmetic.

1. Record the library's provenance, native OS/process architecture and expected
   interface profile. Identify any supplied build receipt or host-header probe
   separately from independent producer build/ABI evidence.
2. Read the resolved adapter policies. Inclusive bounds, nonfinite rejection,
   same-instance retry, parameter purity, identifier syntax and fixed flags are
   declared checker/model choices. Do not infer them from an adapter's IEEE/CIGRE
   name or silently relax them to obtain a passing result.
3. Run `python -m inverter_interface_checks --library PATH --adapter ADAPTER
   --output NEW_REPORT.json` from the checkout. Add `--abi-probe RECEIPT.json`
   only for a supplied matching host-header receipt. State worker and total limits
   before extending them; incomplete results must remain failed.
4. Read the `inverter-interface-report/2` findings and summarize exact failures,
   selected policies, exclusions, platform and identities. Diagnostic text belongs
   only to the channel selected by the actual return: general for 1, error for 2,
   neither for 0/unknown/null Instance. Inactive pointer presence does not make its
   text valid. Preserve raw `fixed_value` and permitted normalization records.
5. Treat software fixtures, canaries and host-header probes as their own software
   evidence. A matching probe does not verify the producer library ABI. A clean
   canary check does not prove memory safety. Make no standards-conformance,
   electrical, numerical-readiness, simulator or cross-platform claim without
   evidence for that specific claim.

Only Model_GetInfo and Model_CheckParameters are called. Do not call FirstCall,
PrintInfo, initialization, outputs, iteration or termination. Do not fetch or
execute an unspecified library, install a simulator, post findings externally or
alter the user's machine configuration. Native process isolation is not a
security sandbox; only run approved code.
