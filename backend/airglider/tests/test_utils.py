from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from pydantic import BaseModel, PrivateAttr

from airglider import (
    now_iso,
    remove_empty_values,
    strip_zero_token_usage,
    to_serializable,
    uuid_8,
)


class TestIdentifiers:
    def test_now_iso_is_a_string(self):
        assert isinstance(now_iso(), str)

    def test_uuid_8_is_eight_chars(self):
        id = uuid_8()
        assert isinstance(id, str)
        assert len(id) == 8


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

    def test_pydantic_private_attr_serialized_recursively(self):
        class Color(Enum):
            RED = "red"

        class M(BaseModel):
            x: int
            _tag: Color = PrivateAttr(default=Color.RED)

        result = to_serializable(M(x=1))
        assert result["_tag"] == "red"

    def test_pydantic_private_attr_is_dict(self):
        class Color(Enum):
            BLUE = "blue"

        class M(BaseModel):
            x: int
            _meta: dict = PrivateAttr(default_factory=lambda: {"color": Color.BLUE, "count": 3})

        result = to_serializable(M(x=1))
        assert result["_meta"] == {"color": "blue", "count": 3}

    def test_pydantic_private_attr_is_dataclass(self):
        @dataclass
        class Point:
            x: int
            y: int

        class M(BaseModel):
            name: str
            _origin: Point = PrivateAttr(default_factory=lambda: Point(0, 0))

        result = to_serializable(M(name="test"))
        assert result["_origin"] == {"x": 0, "y": 0}

    def test_pydantic_private_attr_is_pydantic(self):
        class Inner(BaseModel):
            value: int

        class Outer(BaseModel):
            name: str
            _inner: Inner = PrivateAttr(default_factory=lambda: Inner(value=42))

        result = to_serializable(Outer(name="test"))
        assert result["_inner"] == {"value": 42}

    def test_subclass_fields_preserved_when_typed_as_parent(self):
        """model_dump() on list[Parent] serializes items as Parent, losing subclass
        fields and private attrs. to_serializable must use getattr so the actual
        runtime type is preserved when recursing."""

        class Parent(BaseModel):
            x: int
            _tag: str | None = PrivateAttr(default=None)

        class Child(Parent):
            extra: str

        class Container(BaseModel):
            items: list[Parent]

        child = Child(x=1, extra="subclass_field")
        child._tag = "set_on_child"

        result = to_serializable(Container(items=[child]))
        item = result["items"][0]

        assert item["x"] == 1
        assert item["extra"] == "subclass_field"
        assert item["_tag"] == "set_on_child"

    def test_model_dump_loses_subclass_fields_for_parent_typed_list(self):
        """Demonstrates why model_dump() alone is not enough: items in a
        list[Parent] field are serialized using the declared type, dropping
        Child-specific fields and private attrs entirely."""

        class Parent(BaseModel):
            x: int
            _tag: str | None = PrivateAttr(default=None)

        class Child(Parent):
            extra: str

        class Container(BaseModel):
            items: list[Parent]

        child = Child(x=1, extra="subclass_field")
        child._tag = "set_on_child"

        dumped = Container(items=[child]).model_dump()
        item = dumped["items"][0]

        assert item["x"] == 1
        assert "extra" not in item   # subclass field is lost
        assert "_tag" not in item    # private attr is lost

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

    def test_private_attr_none_stripped_set_kept(self):
        class M(BaseModel):
            x: int
            _set_field: str | None = PrivateAttr(default=None)
            _none_field: str | None = PrivateAttr(default=None)

        m = M(x=1)
        m._set_field = "hello"
        # _none_field stays None

        result = remove_empty_values(to_serializable(m))
        assert result["_set_field"] == "hello"
        assert "_none_field" not in result


class TestStripZeroTokenUsage:
    def test_drops_all_zero_token_usage(self):
        data = {
            "name": "some_step",
            "token_usage": {
                "total": 0,
                "prompt": 0,
                "completion": 0,
                "cached": 0,
                "reasoning_tokens": 0,
                "cost_usd": 0.0,
            },
        }
        assert strip_zero_token_usage(data) == {"name": "some_step"}

    def test_keeps_token_usage_with_any_nonzero_field(self):
        data = {"token_usage": {"total": 5, "prompt": 5, "completion": 0}}
        assert strip_zero_token_usage(data) == data

    def test_only_matches_the_token_usage_key(self):
        # same all-zero shape under a different key must survive — this is
        # a name-scoped rule, not a generic "drop all-zero dicts" rule
        data = {"other_counts": {"a": 0, "b": 0}}
        assert strip_zero_token_usage(data) == data

    def test_recurses_into_nested_steps(self):
        data = {
            "steps": [
                {"name": "db_check", "token_usage": {"total": 0, "prompt": 0}},
                {"name": "llm_call", "token_usage": {"total": 10, "prompt": 10}},
            ]
        }
        assert strip_zero_token_usage(data) == {
            "steps": [
                {"name": "db_check"},
                {"name": "llm_call", "token_usage": {"total": 10, "prompt": 10}},
            ]
        }

    def test_does_not_match_already_empty_dict(self):
        # remove_empty_values would already have dropped this; guard against
        # standalone use where it hasn't
        assert strip_zero_token_usage({"token_usage": {}}) == {"token_usage": {}}
