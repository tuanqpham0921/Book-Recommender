"""Tests for app/common/prompt_loader.py"""
import pytest
from pathlib import Path
from unittest.mock import patch

from app.common.prompt_loader import load_prompt, format_prompt


@pytest.fixture
def prompts_dir(tmp_path):
    with patch("app.common.prompt_loader.PROMPTS_DIR", tmp_path):
        yield tmp_path


def write_prompt(dir: Path, name: str, content: str) -> str:
    path = dir / name
    path.write_text(content, encoding="utf-8")
    return name


class TestLoadPrompt:
    def test_returns_file_content(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "hello world")
        assert load_prompt("test.txt") == "hello world"

    def test_strips_leading_and_trailing_whitespace(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "  \n  hello  \n  ")
        assert load_prompt("test.txt") == "hello"

    def test_raises_when_file_not_found(self, prompts_dir):
        with pytest.raises(FileNotFoundError, match="missing.txt"):
            load_prompt("missing.txt")

    def test_supports_nested_path(self, prompts_dir):
        subdir = prompts_dir / "sub"
        subdir.mkdir()
        write_prompt(subdir, "nested.txt", "nested content")
        assert load_prompt("sub/nested.txt") == "nested content"


class TestFormatPrompt:
    def test_substitutes_variables(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "Hello {NAME}, you are {ROLE}.")
        result = format_prompt("test.txt", NAME="Alice", ROLE="admin")
        assert result == "Hello Alice, you are admin."

    def test_no_variables_returns_content_unchanged(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "No placeholders here.")
        assert format_prompt("test.txt") == "No placeholders here."

    def test_raises_on_missing_variable(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "Hello {NAME}.")
        with pytest.raises(ValueError, match="NAME"):
            format_prompt("test.txt")

    def test_error_message_includes_prompt_path(self, prompts_dir):
        write_prompt(prompts_dir, "my_prompt.txt", "{MISSING}")
        with pytest.raises(ValueError, match="my_prompt.txt"):
            format_prompt("my_prompt.txt")

    def test_extra_kwargs_are_ignored(self, prompts_dir):
        write_prompt(prompts_dir, "test.txt", "Hello {NAME}.")
        result = format_prompt("test.txt", NAME="Bob", UNUSED="ignored")
        assert result == "Hello Bob."

    def test_raises_when_file_not_found(self, prompts_dir):
        with pytest.raises(FileNotFoundError):
            format_prompt("missing.txt", NAME="Bob")
