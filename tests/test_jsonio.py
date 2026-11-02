"""JSON depth and encoding controls independent of decoder recursion limits."""

import codecs
import json
import unittest
from unittest.mock import patch

from inverter_interface_checks import jsonio


def nested(depth, kind, leaf="0"):
    openings = []
    closings = []
    for index in range(depth):
        array = kind == "array" or (kind == "mixed" and index % 2 == 0)
        openings.append("[" if array else '{"child":')
        closings.append("]" if array else "}")
    return "".join(openings) + leaf + "".join(reversed(closings))


class JSONDepth(unittest.TestCase):
    def test_container_depth_boundary(self):
        for kind in ("array", "object", "mixed"):
            for depth in (0, 1, 63, 64):
                with self.subTest(kind=kind, depth=depth):
                    payload = nested(depth, kind)
                    self.assertEqual(jsonio.loads(payload), json.loads(payload))
            with self.subTest(kind=kind, depth=65):
                with self.assertRaisesRegex(ValueError, "JSON nesting"):
                    jsonio.loads(nested(65, kind))

    def test_excessive_depth_is_rejected_before_decoder(self):
        for kind in ("array", "object", "mixed"):
            with self.subTest(kind=kind), patch.object(jsonio.json, "loads") as decoder:
                with self.assertRaisesRegex(ValueError, "JSON nesting"):
                    jsonio.loads(nested(65, kind))
                decoder.assert_not_called()

    def test_strings_do_not_add_container_depth(self):
        values = ("[]{}" * 100, '\\"[{}]', 'ends in \\', '\\\\"[{',
                  "line\nwith [brackets]", "\ud800[{}]")
        for value in values:
            for kind in ("array", "object", "mixed"):
                with self.subTest(value=ascii(value), kind=kind):
                    payload = nested(64, kind, json.dumps(value))
                    self.assertEqual(jsonio.loads(payload), json.loads(payload))
        payload = nested(64, "mixed", '"\\u007b\\u005b\\u0022\\u005c"')
        self.assertEqual(jsonio.loads(payload), json.loads(payload))

    def test_escaped_string_cannot_hide_a_nested_container(self):
        for value in ('ends in \\', 'contains \\"', '[{\\"}]'):
            payload = '["' + json.dumps(value)[1:-1] + '",' + nested(64, "mixed") + ']'
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "JSON nesting"):
                    jsonio.loads(payload)

    def test_sibling_containers_do_not_accumulate_depth(self):
        payload = '[' + ','.join('{"child":[]}' for _ in range(100)) + ']'
        self.assertEqual(jsonio.loads(payload), json.loads(payload))

    def test_supported_byte_encodings_share_the_depth_boundary(self):
        encodings = [(encoding, b"") for encoding in (
            "utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be",
            "utf-32", "utf-32-le", "utf-32-be",
        )]
        encodings += [("utf-16-be", codecs.BOM_UTF16_BE), ("utf-32-be", codecs.BOM_UTF32_BE)]
        for encoding, prefix in encodings:
            for kind in ("array", "object", "mixed"):
                for input_type in (bytes, bytearray):
                    with self.subTest(encoding=encoding, bom=bool(prefix), kind=kind, input_type=input_type):
                        payload = input_type(prefix + nested(64, kind, '"[café]"').encode(encoding))
                        self.assertEqual(jsonio.loads(payload), json.loads(payload))
                        with self.assertRaisesRegex(ValueError, "JSON nesting"):
                            jsonio.loads(input_type(prefix + nested(65, kind).encode(encoding)))

    def test_byte_decoding_preserves_surrogates(self):
        payload = '"\ud800[{}]"'.encode("utf-8", errors="surrogatepass")
        for input_type in (bytes, bytearray):
            with self.subTest(input_type=input_type):
                self.assertEqual(jsonio.loads(input_type(payload)), "\ud800[{}]")

    def test_syntax_type_and_encoding_errors_are_preserved(self):
        for payload in ("[}", "[[]", '{"child":}', '["unterminated]', "[] []", "\ufeff{}"):
            with self.subTest(payload=payload):
                with self.assertRaises(json.JSONDecodeError):
                    jsonio.loads(payload)
        for payload in (None, 1, {}, [], memoryview(b"{}")):
            with self.subTest(input_type=type(payload).__name__):
                with self.assertRaises(TypeError):
                    jsonio.loads(payload)
        with self.assertRaises(UnicodeDecodeError):
            jsonio.loads(b'"\xff"')

    def test_ambiguous_or_nonfinite_values_still_fail_at_the_limit(self):
        for leaf, error in (('{"same":1,"same":2}', "duplicate JSON"),
                            ("NaN", "nonfinite JSON"), ("Infinity", "nonfinite JSON"),
                            ("-Infinity", "nonfinite JSON"), ("1e999", "nonfinite JSON")):
            depth = 63 if leaf.startswith("{") else 64
            with self.subTest(leaf=leaf):
                with self.assertRaisesRegex(ValueError, error):
                    jsonio.loads(nested(depth, "mixed", leaf))
