"""Tests for application.devices.denylist."""

from application.devices.denylist import check_denylist


def test_rm_rf_slash():
    assert check_denylist("rm -rf /") == "rm -rf /"


def test_rm_rf_short_flag_order():
    assert check_denylist("rm -fr /") == "rm -rf /"


def test_rm_rf_home_tilde():
    assert check_denylist("rm -rf ~") == "rm -rf ~"


def test_rm_rf_home_var():
    assert check_denylist("rm -rf $HOME") == "rm -rf $HOME"


def test_fork_bomb():
    assert check_denylist(":(){:|:&};:") == "fork bomb"


def test_fork_bomb_with_spaces():
    assert check_denylist(":(){ :|:& };:") == "fork bomb"


def test_dd_to_block_device():
    assert (
        check_denylist("dd if=/dev/zero of=/dev/sda")
        == "dd to block device"
    )


def test_dd_with_random_to_nvme():
    assert (
        check_denylist("dd if=/dev/random of=/dev/nvme0n1")
        == "dd to block device"
    )


def test_mkfs():
    assert check_denylist("mkfs.ext4 /dev/sda1") == "mkfs"


def test_mkfs_bare():
    assert check_denylist("mkfs /dev/sda1") == "mkfs"


def test_shutdown():
    assert check_denylist("shutdown -h now") == "shutdown"


def test_halt():
    assert check_denylist("halt") == "halt"


def test_poweroff():
    assert check_denylist("poweroff") == "poweroff"


def test_init_0():
    assert check_denylist("init 0") == "init 0/6"


def test_init_6():
    assert check_denylist("init 6") == "init 0/6"


def test_init_other_levels_safe():
    # ``init 3`` shouldn't trigger.
    assert check_denylist("init 3") is None


def test_git_push_force_long():
    assert check_denylist("git push --force origin main") == "git push --force"


def test_git_push_force_with_lease_safe():
    # --force-with-lease is allowed.
    assert check_denylist("git push --force-with-lease origin main") is None


def test_git_push_short_flag():
    assert check_denylist("git push -f origin main") == "git push --force"


def test_git_push_mirror():
    assert check_denylist("git push --mirror origin") == "git push --force"


def test_safe_command_no_match():
    assert check_denylist("ls -la /tmp") is None


def test_compound_with_dangerous_segment():
    # ``echo safe && rm -rf /`` must still trip.
    assert check_denylist("echo safe && rm -rf /") == "rm -rf /"


def test_empty_command():
    assert check_denylist("") is None
