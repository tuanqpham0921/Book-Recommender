import pytest
from common.utils.format import format_exception, remove_json_empty_values


class TestFormatException:
    def test_returns_correct_keys(self):
        try:
            raise ValueError("test error")
        except ValueError as e:
            result = format_exception(e)

        assert result["type"] == "ValueError"
        assert result["message"] == "test error"
        assert "origin" in result
        assert "frames" in result
        assert "traceback" in result

    def test_origin_is_last_frame(self):
        def _inner():
            raise RuntimeError("deep")

        try:
            _inner()
        except RuntimeError as e:
            result = format_exception(e)

        assert result["origin"]["function"] == "_inner"

    def test_frames_have_required_keys(self):
        try:
            raise TypeError("bad type")
        except TypeError as e:
            result = format_exception(e)

        for frame in result["frames"]:
            assert "file" in frame
            assert "line" in frame
            assert "function" in frame
            assert "code" in frame

    def test_traceback_is_list(self):
        try:
            raise Exception("generic")
        except Exception as e:
            result = format_exception(e)

        assert isinstance(result["traceback"], list)


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
