"""Native cdecl layout adapted from OpenIBR's public IEEE/CIGRE 1.1 header.

See third_party/NOTICE.md for the source and license. No packing is applied.
"""

import ctypes as c
import math


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


def native_layout():
    return {
        item.__name__: {
            "size": c.sizeof(item), "alignment": c.alignment(item),
            "offsets": {name: getattr(item, name).offset for name, _ in item._fields_},
        }
        for item in (Signal, DefaultValue, MinMaxValue, Parameter, ModelInfo, Instance)
    }


def read_metadata(library, char_signedness="unsupported"):
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
            names.add(name)
            item = {"name": name, "datatype": datatype,
                    "description": text_at(row.Description), "unit": text_at(row.Unit)}
            if key != "parameters":
                if row.Width < 1 or row.Width > 256:
                    raise ValueError(f"invalid width for {name}")
                item["width"] = row.Width
            else:
                item.update(fixed=bool(row.FixedValue), group=text_at(row.GroupName),
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
