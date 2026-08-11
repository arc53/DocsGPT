"""Tests for application.devices.splitter."""

from application.devices.splitter import head_token, head_tokens, split_command


def test_single_segment():
    assert split_command("ls -la") == ["ls -la"]


def test_and_split():
    assert split_command("ls && rm -rf /") == ["ls", "rm -rf /"]


def test_or_split():
    assert split_command("foo || bar") == ["foo", "bar"]


def test_semicolon_split():
    assert split_command("a; b; c") == ["a", "b", "c"]


def test_pipe_split():
    assert split_command("cat /etc/passwd | grep root") == [
        "cat /etc/passwd",
        "grep root",
    ]


def test_background_amp_split():
    assert split_command("a & b") == ["a", "b"]


def test_pipe_amp_split():
    assert split_command("foo |& bar") == ["foo", "bar"]


def test_newline_split():
    assert split_command("a\nb\nc") == ["a", "b", "c"]


def test_empty_command():
    assert split_command("") == []


def test_whitespace_only():
    assert split_command("   ") == []


def test_head_token_simple():
    assert head_token("ls -la /tmp") == "ls"


def test_head_token_wrapper_timeout():
    assert head_token("timeout 30s ls -la") == "ls"


def test_head_token_wrapper_nice():
    # ``nice -n 10 ls`` should strip ``nice -n 10``.
    assert head_token("nice -n 10 ls") == "ls"


def test_head_token_wrapper_nohup():
    assert head_token("nohup ls") == "ls"


def test_head_token_empty():
    assert head_token("") == ""


def test_head_tokens_compound():
    assert head_tokens("ls && rm -rf / | grep foo") == ["ls", "rm", "grep"]


def test_compound_with_wrappers():
    assert head_tokens("timeout 5 ls && nohup git push") == ["ls", "git"]
