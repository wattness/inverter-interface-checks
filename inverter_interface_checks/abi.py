"""Native cdecl layout adapted from OpenIBR's public IEEE/CIGRE 1.1 header.

See third_party/NOTICE.md for the source and license. No packing is applied.
"""

import ctypes as c
import math
import re
import sys

# Receipt identities also work from wheels, which omit the native source tree.
PROBE_SOURCES = {
    "tests/fixtures/abi_probe.c": "8edeb536d599fdfcf86174aa7f03853d2bb1fb63b353b86f1bfcfd56578fe9a4",
    "third_party/openibr/IEEE_Cigre_DLLInterface.h":
        "3b85aa4372f30c0a291cbe786c2a01a4caeaa22e78cda54ce8e7a112a3822631",
    "third_party/openibr/IEEE_Cigre_DLLInterface_types.h":
        "fed686063e1a021beb8aaae54cfdcaddccb34dc20743753d529e085f0f9b0a3e",
}


class Signal(c.Structure):
    _fields_ = [(name, c.c_void_p) for name in ("Name", "Description", "Unit")] + [
        ("DataType", c.c_int), ("Width", c.c_int)
    ]


SCALARS = {
    1: ("Char_Val", c.c_char),
    2: ("Int8_Val", c.c_int8),
    3: ("Uint8_Val", c.c_uint8),
    4: ("Int16_Val", c.c_int16),
    5: ("Uint16_Val", c.c_uint16),
    6: ("Int32_Val", c.c_int32),
    7: ("Uint32_Val", c.c_uint32),
    8: ("Real32_Val", c.c_float),
    9: ("Real64_Val", c.c_double),
    10: ("Char_Ptr", c.c_void_p),
}


class DefaultValue(c.Union):
    _fields_ = list(SCALARS.values())


class MinMaxValue(c.Union):
    _fields_ = list(SCALARS.values())[:-1]


class Parameter(c.Structure):
    _fields_ = [(name, c.c_void_p) for name in (
        "Name", "GroupName", "Description", "Unit"
    )] + [
        ("DataType", c.c_int), ("FixedValue", c.c_int),
        ("DefaultValue", DefaultValue), ("MinValue", MinMaxValue),
        ("MaxValue", MinMaxValue),
    ]


MODEL_TEXT = (
    "ModelName", "ModelVersion", "ModelDescription", "GeneralInformation",
    "ModelCreated", "ModelCreator", "ModelLastModifiedDate",
    "ModelLastModifiedBy", "ModelModifiedComment", "ModelModifiedHistory",
)


class ModelInfo(c.Structure):
    _fields_ = [("DLLInterfaceVersion", c.c_uint8 * 4)] + [
        (name, c.c_void_p) for name in MODEL_TEXT
    ] + [
        ("FixedStepBaseSampleTime", c.c_double), ("EMT_RMS_Mode", c.c_uint8),
        ("NumInputPorts", c.c_int), ("InputPortsInfo", c.POINTER(Signal)),
        ("NumOutputPorts", c.c_int), ("OutputPortsInfo", c.POINTER(Signal)),
        ("NumParameters", c.c_int), ("ParametersInfo", c.POINTER(Parameter)),
        ("NumIntStates", c.c_int), ("NumFloatStates", c.c_int),
        ("NumDoubleStates", c.c_int),
    ]


class Instance(c.Structure):
    _fields_ = [
        ("ExternalInputs", c.c_void_p), ("ExternalOutputs", c.c_void_p),
        ("Parameters", c.c_void_p), ("Time", c.c_double),
        ("SimTool_EMT_RMS_Mode", c.c_uint8), ("LastErrorMessage", c.c_void_p),
        ("LastGeneralMessage", c.c_void_p), ("IntStates", c.c_void_p),
        ("FloatStates", c.c_void_p), ("DoubleStates", c.c_void_p),
    ]


def text_at(pointer, limit=4096):
    if not pointer:
        return None
    data = bytearray()
    for offset in range(limit):
        value = c.c_ubyte.from_address(pointer + offset).value
        if value == 0:
            return data.decode("utf-8", errors="strict")
        data.append(value)
    raise ValueError(f"text exceeds {limit} bytes")


def union_value(value, datatype, char_signedness="unsupported"):
    result = getattr(value, SCALARS[datatype][0])
    if datatype == 10:
        return text_at(result)
    if isinstance(result, bytes):
        if char_signedness == "unsupported":
            raise ValueError("char parameter signedness must be declared by the adapter")
        result = result[0]
        if char_signedness == "signed" and result >= 128:
            result -= 256
    return result


def layout_of(item):
    """Describe ctypes layout, rather than attest a producer library."""
    return {
        "size": c.sizeof(item), "alignment": c.alignment(item),
        "offsets": {name: getattr(item, name).offset for name, _ in item._fields_},
        "fields": {name: {"offset": getattr(item, name).offset,
                          "size": c.sizeof(field_type), "alignment": c.alignment(field_type)}
                   for name, field_type in item._fields_},
    }


def native_layout():
    return {item.__name__: layout_of(item)
            for item in (Signal, DefaultValue, MinMaxValue, Parameter, ModelInfo, Instance)}


def mixed_probe_layouts():
    rows = {
        "MixedInputs": (True, [{"datatype": 3, "width": 1}, {"datatype": 9, "width": 3},
                               {"datatype": 4, "width": 2}, {"datatype": 8, "width": 1}]),
        "MixedOutputs": (True, [{"datatype": 8, "width": 2}, {"datatype": 3, "width": 1},
                                {"datatype": 9, "width": 1}]),
        "MixedParameters": (False, [{"datatype": 8}, {"datatype": 9}, {"datatype": 6},
                                    {"datatype": 3}, {"datatype": 10}]),
    }
    return {name: layout_of(host_structure(name, fields, ports=ports))
            for name, (ports, fields) in rows.items()}


def compare_native_probe(observation, char_signedness="unsupported"):
    """Compare the host-header observation, never a producer library's ABI.

    OpenIBR uses int ABI fields/results. Its unused enum representations are
    retained as observations; short-enum flags do not shrink those int fields.
    """
    mismatches = []

    def exact(actual, expected):
        if type(actual) is not type(expected):
            return False
        if isinstance(expected, dict):
            return actual.keys() == expected.keys() and all(exact(actual[k], v) for k, v in expected.items())
        if isinstance(expected, list):
            return len(actual) == len(expected) and all(exact(a, b) for a, b in zip(actual, expected))
        return actual == expected

    def compare(path, actual, expected):
        if not exact(actual, expected):
            mismatches.append({"path": path, "native": actual, "ctypes": expected})

    if not isinstance(observation, dict):
        raise ValueError("native probe observation must be an object")
    if char_signedness not in ("unsupported", "signed", "unsigned"):
        raise ValueError("invalid char_signedness")
    compare("schema", observation.get("schema"), "inverter-native-abi-observation/1")
    compare("scope", observation.get("scope"), "host-header-software-probe")
    compare("producer_library_attestation", observation.get("producer_library_attestation"), False)
    compare("endianness", observation.get("endianness"), sys.byteorder)
    compare("char_bits", observation.get("char_bits"), 8)
    compare("datatype_ids", observation.get("datatype_ids"), list(range(1, 11)))
    compare("float_representation", observation.get("float_representation"),
            {"radix": 2, "float_mantissa_bits": 24, "double_mantissa_bits": 53})
    native_scalars, native_aggregates = observation.get("scalars", {}), observation.get("aggregates", {})
    if not isinstance(native_scalars, dict) or not isinstance(native_aggregates, dict):
        raise ValueError("native probe scalars and aggregates must be objects")
    enums = observation.get("enums")
    for name in ("DataType", "ReturnValue"):
        record = enums.get(name) if isinstance(enums, dict) else None
        valid = (isinstance(record, dict) and set(record) == {"size", "alignment", "signedness"}
                 and type(record["size"]) is int and record["size"] > 0
                 and type(record["alignment"]) is int and record["alignment"] > 0
                 and record["signedness"] in ("signed", "unsigned"))
        if not valid:
            mismatches.append({"path": f"enums/{name}", "native": record,
                               "ctypes": "positive integer size/alignment and signed or unsigned"})
    scalars = {"char": (c.c_char, None), "int8_t": (c.c_int8, "signed"),
               "uint8_t": (c.c_uint8, "unsigned"), "int16_t": (c.c_int16, "signed"),
               "uint16_t": (c.c_uint16, "unsigned"), "int32_t": (c.c_int32, "signed"),
               "uint32_t": (c.c_uint32, "unsigned"), "int": (c.c_int, "signed"),
               "long": (c.c_long, "signed"), "float": (c.c_float, "not-applicable"),
               "double": (c.c_double, "not-applicable"), "pointer": (c.c_void_p, "not-applicable")}
    for name, (scalar, signedness) in scalars.items():
        actual = native_scalars.get(name, {})
        if not isinstance(actual, dict):
            raise ValueError("native scalar entries must be objects")
        compare(f"scalars/{name}/size", actual.get("size"), c.sizeof(scalar))
        compare(f"scalars/{name}/alignment", actual.get("alignment"), c.alignment(scalar))
        if name == "char":
            if actual.get("signedness") not in ("signed", "unsigned"):
                mismatches.append({"path": "scalars/char/signedness", "native": actual.get("signedness"),
                                   "ctypes": "signed or unsigned"})
            if char_signedness != "unsupported":
                signedness = char_signedness
        if signedness:
            compare(f"scalars/{name}/signedness", actual.get("signedness"), signedness)
    compare("required/pointer-size", native_scalars.get("pointer", {}).get("size"), 8)
    compare("required/int-size", native_scalars.get("int", {}).get("size"), 4)
    for name, expected in {**native_layout(), **mixed_probe_layouts()}.items():
        actual = native_aggregates.get(name, {})
        if not isinstance(actual, dict):
            raise ValueError("native aggregate entries must be objects")
        for key in ("size", "alignment", "fields"):
            compare(f"aggregates/{name}/{key}", actual.get(key), expected[key])
    return {"matches": not mismatches, "mismatches": mismatches,
            "scope": "host-header-software-probe", "producer_library_attestation": False,
            "char_signedness_policy": char_signedness,
            "enum_policy": "recorded; OpenIBR ABI fields and function returns use int"}


def read_metadata(library, char_signedness="unsupported", *, name_syntax="nonempty",
                  fixed_value_policy="nonzero"):
    get_info = library.Model_GetInfo
    get_info.argtypes = []
    get_info.restype = c.POINTER(ModelInfo)
    pointer = get_info()
    if not pointer:
        raise ValueError("Model_GetInfo returned null")
    version = list(c.cast(pointer, c.POINTER(c.c_uint8 * 4)).contents)
    if version != [1, 1, 0, 0]:
        raise ValueError(f"unsupported interface version {version}")
    info = pointer.contents
    result = {name: text_at(getattr(info, name)) for name in MODEL_TEXT}
    if not result["ModelName"] or not result["ModelVersion"]:
        raise ValueError("model name and version must be nonempty")
    step = info.FixedStepBaseSampleTime
    if not math.isfinite(step) or step <= 0:
        raise ValueError("sample time must be finite and positive")
    if info.EMT_RMS_Mode not in (1, 2, 3):
        raise ValueError("EMT/RMS mode must be 1, 2 or 3")
    result.update(interface_version=version, sample_time=step, mode=info.EMT_RMS_Mode)
    for key, count_name, pointer_name in (
        ("inputs", "NumInputPorts", "InputPortsInfo"),
        ("outputs", "NumOutputPorts", "OutputPortsInfo"),
        ("parameters", "NumParameters", "ParametersInfo"),
    ):
        count, rows = getattr(info, count_name), getattr(info, pointer_name)
        if count < 0 or count > 256 or (count and not rows):
            raise ValueError(f"invalid {key} count or pointer")
        result[key] = []
        names = set()
        for index in range(count):
            row = rows[index]
            name, datatype = text_at(row.Name), row.DataType
            if not name or name in names or datatype not in SCALARS:
                raise ValueError(f"invalid {key} name or datatype at index {index}")
            if name_syntax == "c-identifier-ascii" and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
                raise ValueError(f"invalid C identifier for {key} at index {index}")
            names.add(name)
            item = {"name": name, "datatype": datatype,
                    "description": text_at(row.Description), "unit": text_at(row.Unit)}
            if key != "parameters":
                if row.Width < 1 or row.Width > 256:
                    raise ValueError(f"invalid width for {name}")
                item["width"] = row.Width
            else:
                if fixed_value_policy == "zero-or-one" and row.FixedValue not in (0, 1):
                    raise ValueError(f"invalid FixedValue for {name} under zero-or-one policy")
                item.update(fixed=bool(row.FixedValue), fixed_value=row.FixedValue,
                            group=text_at(row.GroupName),
                            default=union_value(row.DefaultValue, datatype, char_signedness))
                if datatype == 1:
                    item["char_signedness"] = char_signedness
                if datatype != 10:
                    low = union_value(row.MinValue, datatype, char_signedness)
                    high = union_value(row.MaxValue, datatype, char_signedness)
                    if not all(math.isfinite(value) for value in (low, high, item["default"])):
                        raise ValueError(f"nonfinite metadata for {name}")
                    if not low <= item["default"] <= high:
                        raise ValueError(f"invalid bounds or default for {name}")
                    item.update(minimum=low, maximum=high)
                elif item["default"] is None:
                    raise ValueError(f"null string default for {name}")
            result[key].append(item)
    result["states"] = {}
    for name in ("NumIntStates", "NumFloatStates", "NumDoubleStates"):
        count = getattr(info, name)
        if count < 0 or count > 65536:
            raise ValueError(f"invalid state count {name}")
        result["states"][name] = count
    return result


def host_structure(name, rows, ports=False):
    fields = []
    for index, row in enumerate(rows):
        scalar = SCALARS[row["datatype"]][1]
        value_type = scalar * row["width"] if ports and row["width"] > 1 else scalar
        fields.append((f"field_{index}", value_type))
    return type(name, (c.Structure,), {"_fields_": fields})


def host_layouts(metadata):
    result = {}
    for name in ("inputs", "outputs", "parameters"):
        rows = metadata[name]
        structure = host_structure(name, rows, ports=name != "parameters")
        result[name] = {"size": c.sizeof(structure), "alignment": c.alignment(structure),
                        "fields": [{"name": row["name"], "datatype": row["datatype"],
                                    "width": row.get("width", 1),
                                    "offset": getattr(structure, field).offset,
                                    "size": c.sizeof(value_type)}
                                   for row, (field, value_type) in zip(rows, structure._fields_)]}
    return result
