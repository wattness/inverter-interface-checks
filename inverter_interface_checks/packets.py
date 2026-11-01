"""Require complete worker evidence before a successful packet is accepted."""

import ctypes as c
import json
import math

from . import abi
from .contracts import check_expectations


def require(value, message):
    if not value:
        raise ValueError(message)


def text(value, nullable=True):
    return (nullable and value is None) or isinstance(value, str) and len(value.encode("utf-8")) < 4096


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def same(left, right):
    # JSON types matter: a boolean cannot stand in for an integer observation.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def metadata_fields(metadata, adapter):
    require(isinstance(metadata, dict), "missing metadata evidence")
    require(all(name in metadata and text(metadata[name]) for name in abi.MODEL_TEXT), "incomplete model text evidence")
    require(bool(metadata["ModelName"]) and bool(metadata["ModelVersion"]), "missing model name or version")
    require(same(metadata.get("interface_version"), [1, 1, 0, 0]), "invalid interface-version evidence")
    require(number(metadata.get("sample_time")) and metadata["sample_time"] > 0, "invalid sample-time evidence")
    require(integer(metadata.get("mode"), 1, 3), "invalid mode evidence")
    for family in ("inputs", "outputs", "parameters"):
        rows = metadata.get(family)
        require(isinstance(rows, list) and len(rows) <= 256, "invalid metadata row evidence")
        names = set()
        for row in rows:
            require(isinstance(row, dict) and text(row.get("name"), False) and row["name"]
                    and row["name"] not in names, "invalid metadata name evidence")
            names.add(row["name"])
            require(integer(row.get("datatype"), 1, 10), "invalid metadata datatype evidence")
            require(all(key in row and text(row[key]) for key in ("description", "unit")), "missing metadata text evidence")
            if family != "parameters":
                require(integer(row.get("width"), 1, 256), "invalid port-width evidence")
                continue
            require(type(row.get("fixed")) is bool and integer(row.get("fixed_value"), -(2**31), 2**31 - 1)
                    and row["fixed"] == bool(row["fixed_value"]), "invalid fixed-value evidence")
            require("group" in row and text(row["group"]), "missing parameter-group evidence")
            if row["datatype"] == 10:
                require(text(row.get("default"), False), "invalid string-default evidence")
            else:
                require(all(number(row.get(key)) for key in ("minimum", "maximum", "default"))
                        and row["minimum"] <= row["default"] <= row["maximum"], "invalid parameter-bound evidence")
                if row["datatype"] == 1:
                    require(row.get("char_signedness") in ("signed", "unsigned")
                            and row["char_signedness"] == adapter["char_signedness"], "invalid char-signedness evidence")
    states = metadata.get("states")
    require(isinstance(states, dict) and set(states) == {"NumIntStates", "NumFloatStates", "NumDoubleStates"}
            and all(integer(value, 0, 65536) for value in states.values()), "invalid state-count evidence")
    check_expectations(metadata, adapter)


def call_fields(call):
    require(isinstance(call, dict) and type(call.get("return_code")) is int, "missing call-return evidence")
    require(call.get("kind") in ("valid", "invalid", "null_instance", "null_parameters"), "invalid call-kind evidence")
    require(all(key in call and text(call[key]) for key in ("error_message", "general_message")), "missing diagnostic evidence")
    require(all(key in call and (call[key] is None or type(call[key]) is bool)
                for key in ("error_pointer_present", "general_pointer_present")), "missing diagnostic-pointer evidence")
    require("diagnostic_channel" in call and call["diagnostic_channel"] in (None, "error", "general"), "missing diagnostic-channel evidence")
    require(isinstance(call.get("parameter_mutations"), list), "missing mutation evidence")
    checks = call.get("checks")
    require(isinstance(checks, list) and all(isinstance(check, dict) and set(check) == {"check", "ok"}
            and text(check["check"], False) and check["check"] and type(check["ok"]) is bool for check in checks),
            "invalid call-check evidence")
    require(len({check["check"] for check in checks}) == len(checks), "duplicate call-check evidence")


def required_checks(metadata, adapter, call):
    expected = {"return_code", "Instance/guards", "instance_fields_unchanged"}
    buffers = ["ExternalInputs", "ExternalOutputs", "Parameters", "IntStates", "FloatStates", "DoubleStates"]
    buffers += [f"parameter_string[{index}]" for index, row in enumerate(metadata["parameters"]) if row["datatype"] == 10]
    normalization = call["return_code"] in (0, 1) and adapter["parameter_mutation"] == "allow-normalization"
    for name in buffers:
        expected.add(name + "/guards")
        expected.add(name + ("/protected_bytes_unchanged" if name == "Parameters" and normalization else "/unchanged"))
    if normalization:
        for index, row in enumerate(metadata["parameters"]):
            if row["datatype"] == 10:
                continue
            if adapter["nonfinite"] == "reject":
                expected.add(f"parameter[{index}]/normalized_finite")
            if adapter["bounds"] == "inclusive":
                expected.add(f"parameter[{index}]/normalized_bounds")
    if call["return_code"] == 1:
        expected.add("general_message")
    if call["return_code"] == 2 and (call["kind"] == "invalid" and adapter["invalid_message"]
                                    or call["kind"] == "null_parameters" and adapter["null_parameters_message"]):
        expected.add("error_message")
    if call["kind"] == "valid" and adapter["clear_error_on_success"]:
        expected.add("success_error_cleared")
    return expected


def mutation_fields(call, metadata, adapter, checks):
    mutations = call["parameter_mutations"]
    normalization = call["return_code"] in (0, 1) and adapter["parameter_mutation"] == "allow-normalization"
    require(not mutations or normalization, "mutation evidence contradicts the selected policy or return")
    require(not mutations or "Parameters/unchanged" not in checks, "mutation evidence contradicts unchanged parameters")
    indices = set()
    for mutation in mutations:
        require(isinstance(mutation, dict) and set(mutation) == {
            "parameter", "index", "before_hex", "after_hex", "policy"}, "invalid mutation fields")
        index = mutation["index"]
        require(integer(index, 0, len(metadata["parameters"]) - 1) and index not in indices,
                "invalid or duplicate mutation index")
        indices.add(index)
        row = metadata["parameters"][index]
        require(row["datatype"] != 10 and mutation["parameter"] == row["name"]
                and mutation["policy"] == "allow-normalization", "wrong mutation subject or policy")
        scalar = abi.SCALARS[row["datatype"]][1]
        size = c.sizeof(scalar)
        values = []
        for key in ("before_hex", "after_hex"):
            value = mutation[key]
            require(isinstance(value, str) and len(value) == size * 2, "invalid mutation byte width")
            values.append(bytes.fromhex(value))
            require(len(values[-1]) == size, "invalid mutation bytes")
        require(values[0] != values[1], "mutation evidence contains unchanged bytes")
        value = scalar.from_buffer_copy(values[1]).value
        if row["datatype"] == 1:
            value = value[0]
            if row["char_signedness"] == "signed" and value >= 128:
                value -= 256
        require(adapter["nonfinite"] != "reject" or math.isfinite(value), "mutation contradicts finite-value check")
        require(adapter["bounds"] != "inclusive" or row["minimum"] <= value <= row["maximum"],
                "mutation contradicts normalized bounds")


def successful_call(call, kind, metadata, adapter):
    require(call["kind"] == kind, "wrong requested-call evidence")
    expected = (adapter[kind + "_return"] if kind.startswith("null_")
                else adapter["invalid_return"] if kind == "invalid" else adapter["valid_returns"])
    require(call["return_code"] in expected if isinstance(expected, list) else call["return_code"] == expected,
            "successful packet has a rejected return")
    channel = None if kind == "null_instance" else "error" if call["return_code"] == 2 else "general" if call["return_code"] == 1 else None
    require(call["diagnostic_channel"] == channel, "wrong active diagnostic evidence")
    for name in ("error", "general"):
        present, message = call[name + "_pointer_present"], call[name + "_message"]
        require(present is None if kind == "null_instance" else type(present) is bool, "invalid diagnostic-pointer observation")
        require(message is None if channel != name else message is None or present is True, "invalid diagnostic-text observation")
    checks = {item["check"]: item["ok"] for item in call["checks"]}
    require(required_checks(metadata, adapter, call) <= checks.keys(), "missing requested call checks")
    require(all(checks.values()), "successful packet contains failed checks")
    mutation_fields(call, metadata, adapter, checks)
    if "general_message" in checks:
        require(bool(call["general_message"] and call["general_message"].strip()), "missing general-message text")
    if "error_message" in checks:
        require(bool(call["error_message"] and call["error_message"].strip()), "missing error-message text")
    if "success_error_cleared" in checks:
        require(call["error_pointer_present"] is False, "success retained an error pointer")


def validate_result(request, result):
    """Failed native observations remain available; incomplete success is refused."""
    try:
        if "calls" in result:
            require(isinstance(result["calls"], list), "invalid call-list evidence")
            for call in result["calls"]:
                call_fields(call)
        if result["ok"] is False or request.get("action") not in ("metadata", "case"):
            return
        adapter = request["adapter"]
        if request["action"] == "metadata":
            metadata = result.get("metadata")
            metadata_fields(metadata, adapter)
            require(result.get("native_layout_scope") == "ctypes declarations; not producer-library attestation",
                    "missing host-layout scope")
            require(same(result.get("native_layout"), abi.native_layout())
                    and same(result.get("host_layouts"), abi.host_layouts(metadata)), "incomplete host-layout evidence")
            return
        metadata = request["metadata"]
        metadata_fields(metadata, adapter)
        require(result.get("metadata_unchanged") is True, "missing metadata-recheck evidence")
        policy = adapter["recheck_policy"]
        require(result.get("recheck_policy") == policy, "wrong recheck-policy evidence")
        kinds = [request["case"]["kind"]]
        if kinds[0] == "invalid" and policy == "same-instance":
            kinds.append("valid")
        calls = result.get("calls")
        require(isinstance(calls, list) and len(calls) == len(kinds), "missing requested calls")
        for call, kind in zip(calls, kinds):
            successful_call(call, kind, metadata, adapter)
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("incomplete worker evidence") from error
