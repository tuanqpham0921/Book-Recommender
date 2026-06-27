import pytest
from common.utils.format import remove_json_empty_values

class TestToJsonable:
    ...


class TestRemoveJsonEmptyValues:
    def test_removes_none(self):
        assert remove_json_empty_values({"a": None, "b": "val"}) == {"b": "val"}

    def test_removes_empty_string(self):
        assert remove_json_empty_values({"a": "", "b": "x"}) == {"b": "x"}

    def test_removes_empty_list(self):
        assert remove_json_empty_values({"a": [], "b": [1]}) == {"b": [1]}

    def test_removes_empty_dict(self):
        assert remove_json_empty_values({"a": {}, "b": {"c": 1}}) == {"b": {"c": 1}}

    def test_nested_cleanup(self):
        data = {"outer": {"inner": None, "keep": 1}, "empty": {}}
        assert remove_json_empty_values(data) == {"outer": {"keep": 1}}

    def test_list_of_mixed_empties(self):
        assert remove_json_empty_values([None, "a", "", [], {}]) == ["a"]

    def test_preserves_zero_and_false(self):
        assert remove_json_empty_values({"a": 0, "b": False, "c": None}) == {
            "a": 0,
            "b": False,
        }

    def test_scalar_passthrough(self):
        assert remove_json_empty_values("hello") == "hello"
        assert remove_json_empty_values(42) == 42
