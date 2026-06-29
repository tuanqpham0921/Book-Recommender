import json
import builtins
from enum import Enum
from pydantic import BaseModel
from unittest.mock import patch

from common.utils.json_handler import load_json, print_json, save_file


class TestSaveFile:
    def test_writes_json_file(self, tmp_path):
        save_file({"key": "value"}, file_name="out", path=tmp_path)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"key": "value"}

    def test_accepts_filename_with_json_extension(self, tmp_path):
        save_file({"x": 1}, file_name="out.json", path=tmp_path)
        assert (tmp_path / "out.json").exists()

    def test_creates_directory_if_missing(self, tmp_path):
        nested = tmp_path / "a" / "b"
        save_file({"x": 1}, file_name="out", path=nested)
        assert (nested / "out.json").exists()

    def test_remove_empty_drops_none_values(self, tmp_path):
        save_file(
            {"a": 1, "b": None}, file_name="out", path=tmp_path, remove_empty=True
        )
        result = json.loads((tmp_path / "out.json").read_text())
        assert "b" not in result

    def test_remove_empty_false_keeps_none(self, tmp_path):
        save_file(
            {"a": 1, "b": None}, file_name="out", path=tmp_path, remove_empty=False
        )
        result = json.loads((tmp_path / "out.json").read_text())
        assert "b" in result

    def test_serializes_pydantic_model(self, tmp_path):
        class M(BaseModel):
            x: int
            y: str = "hi"

        save_file(M(x=1), file_name="out", path=tmp_path, remove_empty=False)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"x": 1, "y": "hi"}

    def test_serializes_enum(self, tmp_path):
        class Color(Enum):
            RED = "red"

        save_file(
            {"color": Color.RED}, file_name="out", path=tmp_path, remove_empty=False
        )
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"color": "red"}

    def test_serializes_nested_pydantic(self, tmp_path):
        class Inner(BaseModel):
            score: float
            tag: str | None = None

        class Outer(BaseModel):
            name: str
            inner: Inner

        data = Outer(name="book", inner=Inner(score=4.5))
        save_file(data, file_name="out", path=tmp_path, remove_empty=True)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"name": "book", "inner": {"score": 4.5}}

    def test_serializes_nested_dataclass(self, tmp_path):
        from dataclasses import dataclass

        @dataclass
        class Inner:
            score: float
            tag: str | None = None

        @dataclass
        class Outer:
            name: str
            inner: Inner

        data = Outer(name="book", inner=Inner(score=4.5))
        save_file(data, file_name="out", path=tmp_path, remove_empty=False)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"name": "book", "inner": {"score": 4.5, "tag": None}}

    def test_serializes_pydantic_containing_dataclass(self, tmp_path):
        from dataclasses import dataclass

        @dataclass
        class Inner:
            score: float

        class Outer(BaseModel):
            model_config = {"arbitrary_types_allowed": True}
            name: str
            inner: Inner

        data = Outer(name="book", inner=Inner(score=4.5))
        save_file(data, file_name="out", path=tmp_path, remove_empty=False)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"name": "book", "inner": {"score": 4.5}}

    def test_serializes_pydantic_private_attrs(self, tmp_path):
        from pydantic import PrivateAttr

        class M(BaseModel):
            name: str
            _secret: str = PrivateAttr(default="hidden")
            _count: int = PrivateAttr(default=42)

        data = M(name="book")
        save_file(data, file_name="out", path=tmp_path, remove_empty=False)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result["name"] == "book"
        assert result["_secret"] == "hidden"
        assert result["_count"] == 42

    def test_serializes_dataclass_containing_pydantic(self, tmp_path):
        from dataclasses import dataclass
        from pydantic import PrivateAttr

        class Inner(BaseModel):
            score: float
            _secret: str = PrivateAttr(default="hidden")

        @dataclass
        class Outer:
            name: str
            inner: Inner

        data = Outer(name="book", inner=Inner(score=4.5))
        save_file(data, file_name="out", path=tmp_path, remove_empty=False)
        result = json.loads((tmp_path / "out.json").read_text())
        assert result == {"name": "book", "inner": {"score": 4.5, "_secret": "hidden"}}


class TestLoadJson:
    def test_returns_dict(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        result = load_json("data", path=tmp_path)
        assert result == {"key": "value"}

    def test_accepts_filename_with_json_extension(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        result = load_json("data.json", path=tmp_path)
        assert result == {"key": "value"}

    def test_returns_list(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps([1, 2, 3]))
        result = load_json("data", path=tmp_path)
        assert result == [1, 2, 3]

    def test_returns_none_when_file_not_found(self, tmp_path):
        result = load_json("nonexistent", path=tmp_path)
        assert result is None

    def test_nested_data_preserved(self, tmp_path):
        data = {"a": {"b": [1, None, "x"]}}
        f = tmp_path / "data.json"
        f.write_text(json.dumps(data))
        assert load_json("data", path=tmp_path) == data


class TestPrintJson:
    def test_prints_output(self, capsys):
        print_json({"x": 1}, color=False)
        out = capsys.readouterr().out
        assert '"x": 1' in out

    def test_prints_label(self, capsys):
        print_json({"x": 1}, name="MyLabel", color=False)
        out = capsys.readouterr().out
        assert "MyLabel" in out

    def test_no_label_when_name_is_none(self, capsys):
        print_json({"x": 1}, name=None, color=False)
        out = capsys.readouterr().out
        assert "***" not in out

    def test_serializes_non_primitive(self, capsys):
        from enum import Enum

        class Color(Enum):
            RED = "red"

        print_json(Color.RED, color=False)
        out = capsys.readouterr().out
        assert "red" in out

    def test_color_adds_ansi_codes(self, capsys):
        print_json({"x": 1}, color=True)
        out = capsys.readouterr().out
        # pygments injects ANSI escape sequences when color=True
        assert "\x1b[" in out

    def test_color_false_has_no_ansi_codes(self, capsys):
        print_json({"x": 1}, color=False)
        out = capsys.readouterr().out
        assert "\x1b[" not in out

    def test_color_falls_back_gracefully_without_pygments(self, capsys):
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "pygments":
                raise ImportError
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            print_json({"x": 1}, color=True)

        out = capsys.readouterr().out
        assert '"x": 1' in out
        assert "\x1b[" not in out


class TestSaveFileLogger:
    def test_logs_file_path_on_save(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="common.utils.json_handler"):
            save_file({"x": 1}, file_name="out", path=tmp_path)
        assert any("out.json" in m for m in caplog.messages)

    def test_logs_warning_on_missing_file(self, tmp_path, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="common.utils.json_handler"):
            load_json("nonexistent", path=tmp_path)
        assert any("nonexistent" in m for m in caplog.messages)

    def test_logs_file_path_on_load(self, tmp_path, caplog):
        import logging

        (tmp_path / "data.json").write_text('{"x": 1}')
        with caplog.at_level(logging.INFO, logger="common.utils.json_handler"):
            load_json("data", path=tmp_path)
        assert any("data.json" in m for m in caplog.messages)
