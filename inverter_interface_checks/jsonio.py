"""Decode unambiguous, finite JSON at checker input boundaries."""

import json
import math


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
    try:
        return json.loads(data, object_pairs_hook=_object, parse_float=_float, parse_constant=_constant)
    except RecursionError as error:
        raise ValueError("JSON nesting exceeds decoder limits") from error
