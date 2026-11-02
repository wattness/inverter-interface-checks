"""Decode unambiguous, finite JSON at checker input boundaries."""

import json
import math

MAX_JSON_DEPTH = 64


def _check_depth(data):
    depth = 0
    quoted = escaped = False
    for character in data:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError(f"JSON nesting exceeds {MAX_JSON_DEPTH} container levels")
        elif character in "]}":
            depth -= 1


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite JSON number")
    return number


def _constant(value):
    raise ValueError("nonfinite JSON number")


def loads(data):
    if isinstance(data, (bytes, bytearray)):
        data = data.decode(json.detect_encoding(data), "surrogatepass")
    elif not isinstance(data, str):
        raise TypeError("JSON input must be str, bytes or bytearray")
    _check_depth(data)
    try:
        return json.loads(data, object_pairs_hook=_object, parse_float=_float, parse_constant=_constant)
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds decoder limits") from error
