"""Tests for application.devices.normalizer."""

from application.devices.normalizer import normalize_command, normalize_segment


def test_normalize_git_checkout():
    assert normalize_segment("git checkout main -- file.txt") == "git checkout *"


def test_normalize_npm_install():
    assert normalize_segment("npm install foo bar") == "npm install *"


def test_normalize_ls_with_args():
    assert normalize_segment("ls -la /tmp") == "ls *"


def test_normalize_cat_path():
    assert normalize_segment("cat /etc/passwd") == "cat *"


def test_normalize_no_args():
    assert normalize_segment("pwd") == "pwd"


def test_normalize_two_word_no_args():
    # ``git status`` has no additional args; pattern is just ``git status``.
    assert normalize_segment("git status") == "git status"


def test_normalize_empty():
    assert normalize_segment("") == ""


def test_normalize_command_compound_uses_first():
    # First segment only.
    assert normalize_command("ls -la && rm -rf /tmp") == "ls *"


def test_normalize_command_none_when_empty():
    assert normalize_command("") is None


def test_normalize_quoted_args():
    assert normalize_segment('echo "hello world"') == "echo *"


def test_normalize_docker_run():
    assert normalize_segment("docker run -it nginx") == "docker run *"


def test_normalize_kubectl_apply():
    assert normalize_segment("kubectl apply -f deploy.yaml") == "kubectl apply *"


def test_normalize_known_two_word_minimal():
    # Just ``npm`` with no subcmd.
    assert normalize_segment("npm") == "npm"
