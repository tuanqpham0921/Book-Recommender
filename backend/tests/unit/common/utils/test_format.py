from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, PrivateAttr

from common.utils.format import remove_empty_values, to_serializable


class TestToSerializable:
    def test_primitives_pass_through(self):
        assert to_serializable(1) == 1
        assert to_serializable("hello") == "hello"
        assert to_serializable(3.14) == 3.14
        assert to_serializable(None) is None
        assert to_serializable(True) is True

    def test_type_returns_name(self):
        assert to_serializable(int) == "int"
        assert to_serializable(str) == "str"

    def test_enum_returns_value(self):
        class Color(Enum):
            RED = "red"
            BLUE = 2

        assert to_serializable(Color.RED) == "red"
        assert to_serializable(Color.BLUE) == 2
        assert to_serializable(Color) == "Color"

    def test_path_returns_string(self):
        assert to_serializable(Path("/tmp/foo")) == "/tmp/foo"

    def test_exception_returns_dict(self):
        result = to_serializable(ValueError("bad input"))
        assert result == {"type": "ValueError", "message": "bad input"}

    def test_dict_keys_stringified_and_values_converted(self):
        class Color(Enum):
            RED = "red"

        assert to_serializable({1: Color.RED}) == {"1": "red"}

    def test_list_items_converted(self):
        class Color(Enum):
            RED = "red"

        assert to_serializable([Color.RED, 42, "x"]) == ["red", 42, "x"]

    def test_tuple_and_set_converted_to_list(self):
        assert to_serializable((1, 2)) == [1, 2]
        assert sorted(to_serializable({3, 4})) == [3, 4]

    def test_pydantic_model_dumped(self):
        class M(BaseModel):
            x: int
            y: str = "hi"

        assert to_serializable(M(x=1)) == {"x": 1, "y": "hi"}

    def test_pydantic_private_attrs_included(self):
        class M(BaseModel):
            x: int
            _secret: str = PrivateAttr(default="hidden")

        m = M(x=1)
        result = to_serializable(m)
        assert result["x"] == 1
        assert result["_secret"] == "hidden"

    def test_dataclass_fields_converted(self):
        @dataclass
        class Point:
            x: int
            y: int

        assert to_serializable(Point(x=3, y=4)) == {"x": 3, "y": 4}

    def test_nested_dataclass(self):
        @dataclass
        class Inner:
            val: int

        @dataclass
        class Outer:
            inner: Inner

        assert to_serializable(Outer(inner=Inner(val=7))) == {"inner": {"val": 7}}


class TestRemoveEmptyValues:
    def test_removes_none(self):
        assert remove_empty_values({"a": None, "b": "val"}) == {"b": "val"}

    def test_removes_empty_string(self):
        assert remove_empty_values({"a": "", "b": "x"}) == {"b": "x"}

    def test_removes_empty_list(self):
        assert remove_empty_values({"a": [], "b": [1]}) == {"b": [1]}

    def test_removes_empty_dict(self):
        assert remove_empty_values({"a": {}, "b": {"c": 1}}) == {"b": {"c": 1}}

    def test_nested_cleanup(self):
        data = {"outer": {"inner": None, "keep": 1}, "empty": {}}
        assert remove_empty_values(data) == {"outer": {"keep": 1}}

    def test_list_of_mixed_empties(self):
        assert remove_empty_values([None, "a", "", [], {}]) == ["a"]

    def test_preserves_zero_and_false(self):
        assert remove_empty_values({"a": 0, "b": False, "c": None}) == {
            "a": 0,
            "b": False,
        }

    def test_scalar_passthrough(self):
        assert remove_empty_values("hello") == "hello"
        assert remove_empty_values(42) == 42

    def test_pydantic_list(self):
        class M(BaseModel):
            x: int
            y: str = "hi"
            z: list = [None, None, "hello"]

        instance = M(x=1)
        assert remove_empty_values(instance) == instance
