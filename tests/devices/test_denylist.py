"""Tests for application.devices.denylist."""

from application.devices.denylist import check_denylist


def test_rm_rf_slash():
    assert check_denylist("rm -rf /") == "rm -rf /"


def test_rm_rf_short_flag_order():
    assert check_denylist("rm -fr /") == "rm -rf /"


def test_rm_rf_slash_star():
    assert check_denylist("rm -rf /*") == "rm -rf /"


def test_rm_rf_long_flags():
    assert check_denylist("rm --recursive --force /") == "rm -rf /"


def test_rm_rf_no_preserve_root():
    assert check_denylist("rm -rf --no-preserve-root /") == "rm -rf /"


def test_rm_rf_no_preserve_root_before_flags():
    assert check_denylist("rm --no-preserve-root -rf /") == "rm -rf /"


def test_rm_rf_no_preserve_root_slash_star():
    assert check_denylist("rm -rf --no-preserve-root /*") == "rm -rf /"


def test_rm_rf_long_flags_with_no_preserve_root():
    assert (
        check_denylist("rm --recursive --no-preserve-root --force /")
        == "rm -rf /"
    )


def test_rm_separated_flags_r_then_f():
    # ``rm -r -f /`` (flags as separate tokens) must still trip.
    assert check_denylist("rm -r -f /") == "rm -rf /"


def test_rm_separated_flags_f_then_r():
    assert check_denylist("rm -f -r /") == "rm -rf /"


def test_rm_rfv_bundle_root():
    assert check_denylist("rm -rfv /") == "rm -rf /"


def test_rm_short_recursive_long_force():
    assert check_denylist("rm -r --force /") == "rm -rf /"


def test_rm_long_recursive_short_force_slash_star():
    assert check_denylist("rm --recursive -f /*") == "rm -rf /"


def test_rm_rf_tmp_subpath_safe():
    assert check_denylist("rm -rf /tmp/foo") is None


def test_rm_rf_relative_build_safe():
    assert check_denylist("rm -rf ./build") is None


def test_rm_rf_home_subpath_safe():
    assert check_denylist("rm -rf /home/x") is None


def test_rm_recursive_only_safe():
    # Recursive without force isn't the catastrophic root-wipe form.
    assert check_denylist("rm -r /tmp") is None


def test_rm_force_only_slash_safe():
    # Force without recursive (``rm -f /``) fails on a non-empty dir; not denied.
    assert check_denylist("rm -f /") is None


def test_rm_force_only_etc_safe():
    # Force without recursive on a real path is not the root-wipe form.
    assert check_denylist("rm -f /etc/hosts") is None


def test_rm_separated_flags_subpath_safe():
    # Separated recursive+force on a subpath stays safe.
    assert check_denylist("rm -r -f /tmp/x") is None


def test_rm_wrapped_timeout_separated_flags():
    # ``timeout 5 rm -r -f /`` — wrapper + separated flags must still trip.
    assert check_denylist("timeout 5 rm -r -f /") == "rm -rf /"


def test_rm_wrapped_nice_separated_flags():
    assert check_denylist("nice rm -f -r /") == "rm -rf /"


def test_rm_wrapped_nohup_bundle():
    assert check_denylist("nohup rm -rf /") == "rm -rf /"


def test_rm_wrapped_timeout_duration_slash_star():
    # ``timeout 30s rm -rf /*`` — duration token skipped, root-star target.
    assert check_denylist("timeout 30s rm -rf /*") == "rm -rf /"


def test_wrapped_safe_ls_not_denied():
    # ``timeout 5 ls`` is harmless even though it's wrapped.
    assert check_denylist("timeout 5 ls") is None


def test_wrapped_rm_subpath_safe():
    # ``nice rm -rf /tmp/foo`` is a subpath wipe; stays safe.
    assert check_denylist("nice rm -rf /tmp/foo") is None


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
