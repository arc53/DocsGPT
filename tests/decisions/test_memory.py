"""Memory and CPU budgets read from fake /sys and /proc trees."""

import pytest

from docsgpt.decisions.backends.onnx import cpu_budget
from docsgpt.decisions.memory import headroom_mb

MB = 1024 * 1024


def tree(root, files: dict):
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


def meminfo(available_mb: int) -> str:
    return f"MemTotal: 64000000 kB\nMemFree: 1000 kB\nMemAvailable: {available_mb * 1024} kB\n"


@pytest.mark.unit
class TestHeadroom:
    def test_cgroup_v2_counts_anon_and_active_file_only(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/memory.max": str(2048 * MB),
            # inactive_file is page cache the kernel reclaims; memory.current would count it
            "sys/fs/cgroup/memory.stat": f"anon {500 * MB}\nactive_file {100 * MB}\ninactive_file {1400 * MB}\n",
            "sys/fs/cgroup/memory.current": str(2000 * MB),
            "proc/meminfo": meminfo(60000),
        })
        assert headroom_mb(root) == pytest.approx(1448)

    def test_cgroup_v2_without_a_limit_uses_mem_available(self, tmp_path):
        root = tree(tmp_path, {"sys/fs/cgroup/memory.max": "max", "proc/meminfo": meminfo(3000)})
        assert headroom_mb(root) == pytest.approx(3000)

    def test_cgroup_v1(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/memory/memory.limit_in_bytes": str(4096 * MB),
            "sys/fs/cgroup/memory/memory.stat": f"total_rss {1000 * MB}\ntotal_active_file {96 * MB}\ncache 9\n",
        })
        assert headroom_mb(root) == pytest.approx(3000)

    def test_cgroup_v1_unlimited_uses_mem_available(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712",
            "proc/meminfo": meminfo(5000),
        })
        assert headroom_mb(root) == pytest.approx(5000)

    def test_the_host_can_be_tighter_than_the_cgroup(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/memory.max": str(8192 * MB),
            "sys/fs/cgroup/memory.stat": "anon 0\n",
            "proc/meminfo": meminfo(900),
        })
        assert headroom_mb(root) == pytest.approx(900)

    def test_nothing_to_read(self, tmp_path):
        assert headroom_mb(tmp_path) is None


def topology(cpus_to_cores: dict) -> dict:
    files = {}
    for cpu, core in cpus_to_cores.items():
        files[f"sys/devices/system/cpu/cpu{cpu}/topology/core_id"] = str(core)
        files[f"sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id"] = "0"
    return files


@pytest.mark.unit
class TestCpuBudget:
    def test_affinity_without_limits(self, tmp_path):
        assert cpu_budget(tmp_path, cpus=list(range(8))) == 8

    def test_cgroup_v2_quota(self, tmp_path):
        root = tree(tmp_path, {"sys/fs/cgroup/cpu.max": "400000 100000"})
        assert cpu_budget(root, cpus=list(range(48))) == 4

    def test_cgroup_v2_without_quota(self, tmp_path):
        root = tree(tmp_path, {"sys/fs/cgroup/cpu.max": "max 100000"})
        assert cpu_budget(root, cpus=list(range(6))) == 6

    def test_cgroup_v1_quota(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/cpu/cpu.cfs_quota_us": "200000", "sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        })
        assert cpu_budget(root, cpus=list(range(16))) == 2

    def test_cgroup_v1_no_quota(self, tmp_path):
        root = tree(tmp_path, {
            "sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1", "sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000",
        })
        assert cpu_budget(root, cpus=list(range(3))) == 3

    def test_hyperthreads_count_once(self, tmp_path):
        root = tree(tmp_path, topology({i: i % 6 for i in range(12)}))
        assert cpu_budget(root, cpus=list(range(12))) == 6

    def test_at_least_one(self, tmp_path):
        root = tree(tmp_path, {"sys/fs/cgroup/cpu.max": "50000 100000"})
        assert cpu_budget(root, cpus=[0, 1]) == 1
