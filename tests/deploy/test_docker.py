"""The docker CLI calls behind `docsgpt up`, against a fake runner."""

import subprocess
from pathlib import Path

import pytest

from docsgpt.deploy import docker as docker_module
from docsgpt.deploy.docker import DeployError, Docker


class FakeRunner:
    """Answers docker commands from a table of argv prefix -> (code, stdout[, stderr]) and records every call."""

    def __init__(self, answers=None):
        self.answers = list((answers or {}).items())
        self.calls = []

    def __call__(self, args, *, cwd=None, capture=False, check=True):
        self.calls.append((list(args), cwd))
        for prefix, answer in self.answers:
            if list(args[: len(prefix)]) == list(prefix):
                if callable(answer):
                    answer = answer()
                code, out, err = (*answer, "")[:3]
                if check and code != 0:
                    raise DeployError(f"{' '.join(args)} failed")
                return subprocess.CompletedProcess(args, code, stdout=out, stderr=err)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def _docker(runner, platform="linux", which=lambda name: "/usr/bin/docker"):
    return Docker(runner=runner, which=which, sleep=lambda seconds: None, platform=platform)


class TestPreflight:
    def test_docker_missing(self):
        with pytest.raises(DeployError, match="Docker is not installed"):
            _docker(FakeRunner(), which=lambda name: None).preflight()

    def test_daemon_down_on_linux_says_how_to_start_it(self):
        runner = FakeRunner({("docker", "info"): (1, "")})
        with pytest.raises(DeployError, match="systemctl start docker"):
            _docker(runner).preflight()

    def test_no_permission_on_the_socket_says_how_to_get_it(self):
        """A user outside the docker group is not told that Docker is down."""
        denied = "permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock"
        runner = FakeRunner({("docker", "info"): (1, "", denied)})
        with pytest.raises(DeployError, match="docker group"):
            _docker(runner).preflight()

    def test_daemon_down_on_macos_starts_docker_desktop(self):
        state = {"started": False}

        def info():
            return (0, "") if state["started"] else (1, "")

        def start():
            state["started"] = True
            return (0, "")

        runner = FakeRunner(
            {
                ("docker", "info"): info,
                ("open", "-a", "Docker"): start,
                ("docker", "compose", "version"): (0, "v2.39.1-desktop.1\n"),
            }
        )
        _docker(runner, platform="darwin").preflight()
        assert (["open", "-a", "Docker"], None) in runner.calls

    @pytest.mark.parametrize("version", ["v2.23.0", "2.20.2"])
    def test_compose_too_old(self, version):
        runner = FakeRunner({("docker", "compose", "version"): (0, version + "\n")})
        with pytest.raises(DeployError, match="2.24"):
            _docker(runner).preflight()

    def test_compose_missing(self):
        runner = FakeRunner({("docker", "compose", "version"): (1, "")})
        with pytest.raises(DeployError, match="Docker Compose"):
            _docker(runner).preflight()

    @pytest.mark.parametrize("version", ["v2.24.0", "2.39.1-desktop.1", "5.5.1"])
    def test_compose_new_enough(self, version):
        runner = FakeRunner({("docker", "compose", "version"): (0, version + "\n")})
        _docker(runner).preflight()


class TestQueries:
    def test_compose_runs_in_the_stack_directory(self, tmp_path):
        runner = FakeRunner()
        _docker(runner).compose(tmp_path, "up", "-d")
        assert runner.calls == [(["docker", "compose", "up", "-d"], tmp_path)]

    def test_volume_exists(self):
        runner = FakeRunner({("docker", "volume", "inspect", "docsgpt_postgres_data"): (0, "[]")})
        assert _docker(runner).volume_exists("docsgpt_postgres_data")
        assert not _docker(FakeRunner({("docker", "volume"): (1, "")})).volume_exists("docsgpt_postgres_data")

    def test_project_directories(self):
        runner = FakeRunner({("docker", "ps"): (0, "/srv/old\n/srv/old\n\n/home/me/.docsgpt/server\n")})
        assert _docker(runner).project_dirs("docsgpt") == {Path("/srv/old"), Path("/home/me/.docsgpt/server")}
        args = runner.calls[0][0]
        assert "label=com.docker.compose.project=docsgpt" in args


class TestWaitHealthy:
    def test_succeeds_once_the_api_answers(self):
        attempts = {"n": 0}

        def opener(url, timeout):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OSError("connection refused")
            return _Response(200)

        clock = iter(range(0, 1000, 2))
        assert docker_module.wait_healthy("http://127.0.0.1:7091/api/health", 60, opener=opener,
                                          sleep=lambda s: None, clock=lambda: next(clock))
        assert attempts["n"] == 3

    def test_gives_up_after_the_timeout(self):
        def opener(url, timeout):
            raise OSError("connection refused")

        clock = iter(range(0, 1000, 10))
        assert not docker_module.wait_healthy("http://127.0.0.1:7091/api/health", 30, opener=opener,
                                              sleep=lambda s: None, clock=lambda: next(clock))


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
