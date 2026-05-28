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


def test_normalize_command_compound_joins_all_segments():
    # All segments normalized and joined; not just the first.
    assert normalize_command("ls -la && rm -rf /tmp") == "ls * && rm *"


def test_normalize_command_compound_distinguishes_tail():
    # Sticky for ``ls /tmp && whoami`` must not match ``ls /tmp && rm /tmp/x``.
    assert normalize_command("ls /tmp && whoami") == "ls * && whoami"
    assert (
        normalize_command("ls /tmp && rm /tmp/x")
        != normalize_command("ls /tmp && whoami")
    )


def test_normalize_command_single_segment_unchanged():
    # A non-compound command yields just its own pattern (no `` && ``).
    assert normalize_command("ls -la /tmp") == "ls *"


def test_normalize_command_skips_empty_segments():
    # Trailing/empty connector segments are dropped, not joined as blanks.
    assert normalize_command("ls -la && ") == "ls *"


def test_normalize_command_none_when_empty():
    assert normalize_command("") is None


def test_normalize_command_none_when_only_connectors():
    assert normalize_command("&& ;") is None


def test_normalize_quoted_args():
    assert normalize_segment('echo "hello world"') == "echo *"


def test_normalize_docker_run():
    assert normalize_segment("docker run -it nginx") == "docker run *"


def test_normalize_kubectl_apply():
    assert normalize_segment("kubectl apply -f deploy.yaml") == "kubectl apply *"


def test_normalize_known_two_word_minimal():
    # Just ``npm`` with no subcmd.
    assert normalize_segment("npm") == "npm"
