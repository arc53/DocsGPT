"""Reading and updating the stack's .env without losing what the user wrote."""

import os
import sys

import pytest

from docsgpt.deploy import envfile


class TestRead:
    def test_comments_blanks_quotes_and_export(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text(
            "# settings\n"
            "\n"
            "LLM_PROVIDER=openai\n"
            "export API_KEY='sk-123'\n"
            'LLM_NAME="gpt 5"\n'
            "EMPTY=\n"
            "not a line\n"
        )
        assert envfile.read(path) == {
            "LLM_PROVIDER": "openai",
            "API_KEY": "sk-123",
            "LLM_NAME": "gpt 5",
            "EMPTY": "",
        }

    def test_a_missing_file_is_empty(self, tmp_path):
        assert envfile.read(tmp_path / ".env") == {}

    def test_the_last_duplicate_wins(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("A=1\nA=2\n")
        assert envfile.read(path) == {"A": "2"}


class TestUpdate:
    def test_changes_values_in_place_and_keeps_everything_else(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("# my settings\nLLM_PROVIDER=openai\n\nCUSTOM=keep me\nDOCSGPT_IMAGE_TAG=0.19.0\n")
        envfile.update(path, {"DOCSGPT_IMAGE_TAG": "0.21.0"})
        assert path.read_text() == "# my settings\nLLM_PROVIDER=openai\n\nCUSTOM=keep me\nDOCSGPT_IMAGE_TAG=0.21.0\n"

    def test_appends_new_keys_and_removes_none(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("A=1\nB=2")
        envfile.update(path, {"B": None, "C": "3"})
        assert path.read_text() == "A=1\nC=3\n"

    def test_duplicates_collapse_to_the_first_line(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("A=1\nX=y\nA=2\n")
        envfile.update(path, {"A": "3"})
        assert path.read_text() == "A=3\nX=y\n"

    @pytest.mark.parametrize("value", ["plain", "with space", "hash # inside", "it's", 'say "hi"', "back\\slash", ""])
    def test_values_round_trip(self, tmp_path, value):
        path = tmp_path / ".env"
        envfile.update(path, {"VALUE": value})
        assert envfile.read(path)["VALUE"] == value

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
    def test_a_new_file_is_private(self, tmp_path):
        path = tmp_path / "stack" / ".env"
        envfile.update(path, {"JWT_SECRET_KEY": "s"})
        assert oct(os.stat(path).st_mode & 0o777) == oct(0o600)

    def test_rejects_a_newline_in_a_value(self, tmp_path):
        with pytest.raises(ValueError, match="newline"):
            envfile.update(tmp_path / ".env", {"A": "1\n2"})
