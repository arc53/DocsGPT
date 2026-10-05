"""scripts/build_daytona_snapshot.py builds its image from the sandbox manifest.

The image is built with the real ``daytona.Image`` (pure, no API call) and
inspected through ``Image.dockerfile()``; the Daytona client is a fake, so no
snapshot is created and no API key is used.
"""

from __future__ import annotations

import base64
import importlib.util
import re
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from docsgpt.core.settings import settings
from docsgpt.sandbox import manifest

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def snap():
    path = _REPO / "scripts" / "build_daytona_snapshot.py"
    spec = importlib.util.spec_from_file_location("build_daytona_snapshot", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _embedded_files(dockerfile: str) -> dict:
    """Decode the files the image writes from base64 RUN lines: {dest: (bytes, mode)}."""
    files = {}
    for match in re.finditer(r"echo (\S+) \| base64 -d > (\S+) && chmod (\d+) \S+", dockerfile):
        files[match.group(2)] = (base64.b64decode(match.group(1)), match.group(3))
    return files


# -- The image -----------------------------------------------------------------


def test_image_starts_from_debian_slim_with_build_tools(snap):
    dockerfile = snap.build_image("3.12").dockerfile()
    assert dockerfile.startswith("FROM python:3.12")
    assert "-slim-bookworm" in dockerfile.splitlines()[0]
    assert "build-essential" in dockerfile


def test_image_sets_the_manifest_env_before_installing(snap):
    dockerfile = snap.build_image("3.12").dockerfile()
    for name, value in manifest.ENV.items():
        assert f"ENV {name}={shlex.quote(value)}" in dockerfile
    assert dockerfile.index("ENV PIP_ROOT_USER_ACTION") < dockerfile.index("python -m pip install")


def test_image_runs_the_system_install_as_one_layer(snap):
    dockerfile = snap.build_image("3.12").dockerfile()
    assert f"RUN {manifest.install_system_one_liner()}\n" in dockerfile
    assert dockerfile.index("apt-get install -y --no-install-recommends") < dockerfile.index("python -m pip install")


def test_image_pip_installs_every_sandbox_pin_without_cache(snap):
    dockerfile = snap.build_image("3.12").dockerfile()
    line = next(x for x in dockerfile.splitlines() if x.startswith("RUN python -m pip install"))
    assert line.endswith("--no-cache-dir")
    for spec in manifest.pip_specs():
        assert spec in line
    for runner_only in manifest.RUNNER_PIP_PACKAGES:
        assert runner_only["spec"] not in line


def test_image_bakes_the_helpers_smoke_test_and_manifest(snap):
    """Embedded from base64, so no local path (the repo may sit under a path with spaces) reaches a COPY."""
    dockerfile = snap.build_image("3.12").dockerfile()
    assert "COPY " not in dockerfile
    files = _embedded_files(dockerfile)
    sandbox = _REPO / "deployment" / "sandbox"
    for name, source in manifest.HELPERS.items():
        data, mode = files[f"/usr/local/bin/{name}"]
        assert data == (sandbox / source).read_bytes()
        assert mode == "0755"
    assert files["/opt/docsgpt/smoke_test.py"][0] == (sandbox / "smoke_test.py").read_bytes()
    assert files["/opt/docsgpt/manifest.json"][0].decode() == manifest.render_manifest_json()


def test_image_honours_the_python_series(snap):
    assert snap.build_image("3.13").dockerfile().startswith("FROM python:3.13")


# -- Arguments -----------------------------------------------------------------


def test_defaults_double_the_daytona_sandbox_resources(snap):
    args = snap.parse_args([])
    assert args.name == "docsgpt-sandbox-py312-v2"
    assert (args.cpu, args.memory, args.disk) == (2, 2, 6)
    assert args.timeout == 0
    assert args.smoke is False


def test_resource_flags_override_the_defaults(snap):
    args = snap.parse_args(["--cpu", "4", "--memory", "8", "--disk", "10", "--timeout", "1800", "--smoke"])
    assert (args.cpu, args.memory, args.disk, args.timeout, args.smoke) == (4, 8, 10, 1800, True)


@pytest.mark.parametrize("flag", ["--cpu", "--memory", "--disk"])
@pytest.mark.parametrize("value,message", [("0", "greater than 0"), ("abc", "not an integer")])
def test_resource_flags_must_be_positive_integers(snap, flag, value, message, capsys):
    with pytest.raises(SystemExit):
        snap.parse_args([flag, value])
    assert message in capsys.readouterr().err


def test_dockerfile_flag_prints_without_an_api_key(snap, monkeypatch, capsys):
    monkeypatch.setattr(settings, "DAYTONA_API_KEY", None, raising=False)
    assert snap.main(["--dockerfile"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("FROM python:3.12")
    assert manifest.install_system_one_liner() in out


# -- Building and smoke-testing against a fake Daytona -------------------------


class _NotFound(Exception):
    pass


_NotFound.__name__ = "DaytonaNotFoundError"


class _FakeSnapshots:
    def __init__(self, existing=False):
        self.existing = existing
        self.created = []

    def get(self, name):
        if self.existing:
            return SimpleNamespace(name=name, state="active")
        raise _NotFound("snapshot not found")

    def create(self, params, on_logs=None, timeout=None):
        self.created.append((params, timeout))
        return SimpleNamespace(name=params.name, state="active")


class _FakeClient:
    def __init__(self, existing=False, smoke_exit=0):
        self.snapshot = _FakeSnapshots(existing)
        self.smoke_exit = smoke_exit
        self.sandboxes = []
        self.deleted = []

    def create(self, params, timeout=None):
        sandbox = SimpleNamespace(params=params, commands=[])

        def exec_(command, timeout=None):
            sandbox.commands.append((command, timeout))
            return SimpleNamespace(exit_code=self.smoke_exit, result="PASS imports\nOK: 0 failed")

        sandbox.process = SimpleNamespace(exec=exec_)
        self.sandboxes.append(sandbox)
        return sandbox

    def delete(self, sandbox):
        self.deleted.append(sandbox)


@pytest.fixture
def fake_client(snap, monkeypatch):
    holder = {}

    def factory(existing=False, smoke_exit=0):
        client = _FakeClient(existing, smoke_exit)
        holder["client"] = client
        monkeypatch.setattr(snap, "make_client", lambda: client)
        return client

    monkeypatch.setattr(settings, "DAYTONA_API_KEY", "test-key", raising=False)
    return factory


def test_main_requires_an_api_key(snap, monkeypatch):
    monkeypatch.setattr(settings, "DAYTONA_API_KEY", None, raising=False)
    assert snap.main([]) == 2


def test_main_creates_the_snapshot_with_the_doubled_resources(snap, fake_client, capsys):
    client = fake_client()
    assert snap.main([]) == 0
    params, timeout = client.snapshot.created[0]
    assert params.name == "docsgpt-sandbox-py312-v2"
    assert (params.resources.cpu, params.resources.memory, params.resources.disk) == (2, 2, 6)
    assert timeout == 0
    assert params.image.dockerfile() == snap.build_image("3.12").dockerfile()
    assert not client.sandboxes, "no smoke run unless asked"
    assert "DAYTONA_SNAPSHOT=docsgpt-sandbox-py312-v2" in capsys.readouterr().out


def test_main_skips_an_existing_snapshot(snap, fake_client):
    client = fake_client(existing=True)
    assert snap.main(["--name", "already-there"]) == 0
    assert client.snapshot.created == []


def test_smoke_runs_the_baked_test_in_a_sandbox_and_deletes_it(snap, fake_client, capsys):
    client = fake_client()
    assert snap.main(["--smoke"]) == 0
    sandbox = client.sandboxes[0]
    assert sandbox.params.snapshot == "docsgpt-sandbox-py312-v2"
    assert sandbox.commands[0][0] == "python /opt/docsgpt/smoke_test.py"
    assert client.deleted == [sandbox]
    assert "OK: 0 failed" in capsys.readouterr().out


def test_smoke_runs_against_an_existing_snapshot(snap, fake_client):
    client = fake_client(existing=True)
    assert snap.main(["--smoke"]) == 0
    assert client.snapshot.created == []
    assert len(client.sandboxes) == 1


def test_smoke_failure_fails_the_run_and_still_cleans_up(snap, fake_client):
    client = fake_client(smoke_exit=1)
    assert snap.main(["--smoke"]) == 1
    assert client.deleted == client.sandboxes
