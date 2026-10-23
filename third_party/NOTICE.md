# Third-party interface declarations

`openibr/IEEE_Cigre_DLLInterface.h` and
`openibr/IEEE_Cigre_DLLInterface_types.h` are unmodified copies from
[HeronPower/OpenIBR](https://github.com/HeronPower/OpenIBR), public commit
`5e2396cef8e57765c6a8fefe34fc379c3a60c163`, under Apache-2.0. Their original
comments and notices remain intact. The repository's LICENSE supplies that
license.

The repository-level [OpenIBR NOTICE](openibr/NOTICE), including its original
copyright attribution, is also retained unmodified.

| File | SHA256 |
|---|---|
| IEEE_Cigre_DLLInterface.h | `3b85aa4372f30c0a291cbe786c2a01a4caeaa22e78cda54ce8e7a112a3822631` |
| IEEE_Cigre_DLLInterface_types.h | `fed686063e1a021beb8aaae54cfdcaddccb34dc20743753d529e085f0f9b0a3e` |

`inverter_interface_checks/abi.py` adapts the declarations into Python ctypes
structures, using bounded text-pointer reads and named metadata-derived host
fields. This adaptation was written by Wattness. The software fixtures are
independently written by Wattness; they contain no OpenIBR controller code.

The copied header cites CIGRE Technical Brochure 958 and the RTE/TU Delft import
tool. Those citations are source attribution, not an independent verification
of the brochure or a formal conformance claim.
