"""`docsgpt up` and the commands that manage the stack, against a fake Docker."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from docsgpt import cli
from docsgpt.deploy import commands, envfile, stack
from docsgpt.deploy.docker import DeployError

EVERY_PROFILE = ["--profile", "https"]


class FakeDocker:
    def __init__(self, volumes=(), project_dirs=()):
        self.volumes = set(volumes)
        self.dirs = {Path(d) for d in project_dirs}
        self.calls = []
        self.preflights = 0

    def preflight(self, interactive=False):
        self.preflights += 1

    def compose(self, directory, *args, capture=False, check=True):
        self.calls.append((Path(directory), list(args)))
        if "down" in args and "-v" in args:
            self.volumes.clear()
        return subprocess.CompletedProcess(["docker", "compose", *args], 0, stdout="", stderr="")

    def volume_exists(self, name):
        return name in self.volumes

    def project_dirs(self, project):
        return set(self.dirs)


class FakePrompter:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.questions = []

    def _next(self, question):
        self.questions.append(question)
        if not self.answers:
            raise AssertionError(f"unexpected question: {question}")
        return self.answers.pop(0)

    def choose(self, question, options, default):
        return self._next(question)

    def text(self, question, default=None, secret=False):
        return self._next(question)

    def confirm(self, question, default=False):
        return self._next(question)


def _context(docker=None, prompter=None, interactive=False, healthy=True, **overrides):
    context = commands.Context(
        docker=docker or FakeDocker(),
        prompter=prompter or FakePrompter(),
        interactive=interactive,
        version="0.21.0",
        lan_ip=lambda: "192.168.1.10",
        wait=lambda url, timeout: healthy,
        open_browser=lambda url: None,
    )
    for key, value in overrides.items():
        setattr(context, key, value)
    return context


def _run(argv, context):
    args = cli.build_parser().parse_args(argv)
    return args.func(args, context)


class TestUpFirstInstall:
    def test_yes_installs_locally_with_the_public_api(self, tmp_path, capsys):
        docker = FakeDocker()
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context(docker)) == 0

        assert (tmp_path / "docker-compose.yaml").read_text() == stack.compose_source().read_text()
        env = envfile.read(tmp_path / ".env")
        assert env["DOCSGPT_IMAGE_TAG"] == "0.21.0"
        assert env["DOCSGPT_BIND"] == "127.0.0.1"
        assert env["LLM_PROVIDER"] == "docsgpt"
        assert env["INTERNAL_KEY"] and env["JWT_SECRET_KEY"] and env["POSTGRES_PASSWORD"]
        assert docker.preflights == 1
        assert docker.calls == [(tmp_path, ["up", "-d", "--remove-orphans"])]
        record = json.loads((tmp_path / "install.json").read_text())
        assert record["version"] == "0.21.0"
        assert "http://localhost:7091" in capsys.readouterr().out

    def test_interactive_asks_who_reaches_it_and_which_model(self, tmp_path, capsys):
        prompter = FakePrompter(["network", "anthropic", "sk-ant"])
        assert _run(["up", "--dir", str(tmp_path)], _context(prompter=prompter, interactive=True)) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["DOCSGPT_BIND"] == "0.0.0.0"
        assert env["AUTH_TYPE"] == "simple_jwt"
        assert env["LLM_PROVIDER"] == "anthropic"
        assert env["API_KEY"] == "sk-ant"
        out = capsys.readouterr().out
        assert "http://192.168.1.10:7091" in out
        assert stack.simple_jwt_token(env["JWT_SECRET_KEY"]) in out

    def test_flags_answer_the_questions(self, tmp_path):
        argv = ["up", "--dir", str(tmp_path), "--domain", "docs.example.com", "--provider", "openai", "--api-key", "sk"]
        assert _run(argv, _context(interactive=True)) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["COMPOSE_PROFILES"] == "https"
        assert env["DOCSGPT_DOMAIN"] == "docs.example.com"
        assert env["LLM_PROVIDER"] == "openai"

    def test_a_missing_api_key_is_an_error_without_a_terminal(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DOCSGPT_API_KEY", raising=False)
        with pytest.raises(DeployError, match="API key"):
            _run(["up", "--yes", "--dir", str(tmp_path), "--provider", "openai"], _context())

    def test_the_api_key_can_come_from_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DOCSGPT_API_KEY", "sk-env")
        assert _run(["up", "--yes", "--dir", str(tmp_path), "--provider", "openai"], _context()) == 0
        assert envfile.read(tmp_path / ".env")["API_KEY"] == "sk-env"

    def test_an_existing_database_keeps_its_password(self, tmp_path):
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context(docker)) == 0
        assert "POSTGRES_PASSWORD" not in envfile.read(tmp_path / ".env")

    def test_image_tag_and_docling(self, tmp_path):
        argv = ["up", "--yes", "--dir", str(tmp_path), "--image-tag", "develop", "--docling"]
        docker = FakeDocker()
        assert _run(argv, _context(docker)) == 0
        env = envfile.read(tmp_path / ".env")
        assert env["DOCSGPT_IMAGE_TAG"] == "develop"
        assert env["DOCSGPT_IMAGE_VARIANT"] == "-docling"
        # A moving tag is pulled every time, not only when missing.
        assert (tmp_path, ["up", "-d", "--remove-orphans", "--pull", "always"]) in docker.calls

    def test_network_mode_warns_about_plain_http_before_starting(self, tmp_path, capsys):
        """The token travels as readable text, so say so before the stack is up, not only after."""
        docker = FakeDocker()
        assert _run(["up", "--yes", "--dir", str(tmp_path), "--expose", "network"], _context(docker)) == 0
        err = capsys.readouterr().err
        assert "plain HTTP" in err
        assert "--domain" in err

    def test_a_local_install_does_not_warn(self, tmp_path, capsys):
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context()) == 0
        assert "plain HTTP" not in capsys.readouterr().err

    def test_an_unhealthy_start_points_at_the_logs(self, tmp_path, capsys):
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context(healthy=False)) == 1
        assert "docsgpt logs" in capsys.readouterr().err
        assert not (tmp_path / "install.json").exists()


class TestUpAgain:
    def test_keeps_the_settings_and_moves_the_version(self, tmp_path):
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context()) == 0
        before = envfile.read(tmp_path / ".env")
        envfile.update(tmp_path / ".env", {"CUSTOM": "mine"})

        context = _context(interactive=True, docker=FakeDocker(volumes={"docsgpt_postgres_data"}))
        context.version = "0.22.0"
        assert _run(["up", "--dir", str(tmp_path)], context) == 0
        after = envfile.read(tmp_path / ".env")
        assert after["DOCSGPT_IMAGE_TAG"] == "0.22.0"
        assert after["CUSTOM"] == "mine"
        for key in ("INTERNAL_KEY", "JWT_SECRET_KEY", "POSTGRES_PASSWORD"):
            assert after[key] == before[key]
        assert context.prompter.questions == [], "a configured install is not asked again"

    def test_leaving_the_domain_removes_caddy_before_starting(self, tmp_path):
        """With the https profile off, `up --remove-orphans` alone would leave Caddy on ports 80 and 443."""
        assert _run(["up", "--yes", "--dir", str(tmp_path), "--domain", "docs.example.com"], _context()) == 0
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        assert _run(["up", "--yes", "--dir", str(tmp_path), "--expose", "local"], _context(docker)) == 0
        assert docker.calls == [
            (tmp_path, [*EVERY_PROFILE, "rm", "--stop", "--force", "caddy"]),
            (tmp_path, ["up", "-d", "--remove-orphans"]),
        ]

    def test_staying_on_the_domain_leaves_caddy_alone(self, tmp_path):
        assert _run(["up", "--yes", "--dir", str(tmp_path), "--domain", "docs.example.com"], _context()) == 0
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context(docker)) == 0
        assert docker.calls == [(tmp_path, ["up", "-d", "--remove-orphans"])]

    def test_another_projects_containers_need_consent(self, tmp_path):
        docker = FakeDocker(project_dirs={"/srv/old-docsgpt"})
        with pytest.raises(DeployError, match="--adopt"):
            _run(["up", "--yes", "--dir", str(tmp_path)], _context(docker))
        assert docker.calls == []
        assert _run(["up", "--yes", "--adopt", "--dir", str(tmp_path)], _context(docker)) == 0

    def test_adopting_recreates_every_container(self, tmp_path):
        """Compose keeps unchanged containers, and with them the old folder's label; the next up would ask again."""
        docker = FakeDocker(project_dirs={"/srv/old-docsgpt"})
        assert _run(["up", "--yes", "--adopt", "--dir", str(tmp_path)], _context(docker)) == 0
        assert docker.calls == [(tmp_path, ["up", "-d", "--remove-orphans", "--force-recreate"])]

    def test_containers_from_this_folder_are_not_recreated(self, tmp_path):
        docker = FakeDocker(project_dirs={str(tmp_path)})
        assert _run(["up", "--yes", "--dir", str(tmp_path)], _context(docker)) == 0
        assert docker.calls == [(tmp_path, ["up", "-d", "--remove-orphans"])]

    def test_consent_can_be_given_at_the_prompt(self, tmp_path):
        docker = FakeDocker(project_dirs={"/srv/old-docsgpt"})
        prompter = FakePrompter([True, "local", "docsgpt"])
        assert _run(["up", "--dir", str(tmp_path)], _context(docker, prompter, interactive=True)) == 0


class TestManage:
    @staticmethod
    def _installed(tmp_path, *extra):
        assert _run(["up", "--yes", "--dir", str(tmp_path), *extra], _context()) == 0

    def test_down_includes_caddy(self, tmp_path):
        self._installed(tmp_path)
        docker = FakeDocker()
        assert _run(["down", "--dir", str(tmp_path)], _context(docker)) == 0
        assert docker.calls == [(tmp_path, [*EVERY_PROFILE, "down"])]

    def test_commands_on_a_missing_install(self, tmp_path, capsys):
        assert _run(["status", "--dir", str(tmp_path)], _context()) == 1
        assert "docsgpt up" in capsys.readouterr().err

    def test_status(self, tmp_path, capsys):
        self._installed(tmp_path)
        docker = FakeDocker()
        assert _run(["status", "--dir", str(tmp_path)], _context(docker)) == 0
        out = capsys.readouterr().out
        assert "0.21.0" in out and "http://localhost:7091" in out
        assert (tmp_path, ["ps"]) in docker.calls

    def test_logs_pass_through(self, tmp_path):
        self._installed(tmp_path)
        docker = FakeDocker()
        assert _run(["logs", "--dir", str(tmp_path), "-f", "--tail", "50", "backend"], _context(docker)) == 0
        assert docker.calls == [(tmp_path, ["logs", "--follow", "--tail", "50", "backend"])]

    def test_token(self, tmp_path, capsys):
        self._installed(tmp_path, "--expose", "network")
        capsys.readouterr()
        assert _run(["token", "--dir", str(tmp_path)], _context()) == 0
        secret = envfile.read(tmp_path / ".env")["JWT_SECRET_KEY"]
        assert capsys.readouterr().out.strip() == stack.simple_jwt_token(secret)

    def test_no_token_without_simple_jwt(self, tmp_path, capsys):
        self._installed(tmp_path)
        assert _run(["token", "--dir", str(tmp_path)], _context()) == 1
        assert "AUTH_TYPE" in capsys.readouterr().err

    def test_env_get_and_set(self, tmp_path, capsys):
        self._installed(tmp_path)
        capsys.readouterr()
        assert _run(["env", "--dir", str(tmp_path), "set", "LLM_NAME=gpt-5.5", "OCR_ENABLED=true"], _context()) == 0
        assert "docsgpt up" in capsys.readouterr().out
        assert _run(["env", "--dir", str(tmp_path), "get", "LLM_NAME"], _context()) == 0
        assert capsys.readouterr().out.strip() == "gpt-5.5"
        assert _run(["env", "--dir", str(tmp_path), "get", "NOPE"], _context()) == 1
        with pytest.raises(DeployError, match="KEY=VALUE"):
            _run(["env", "--dir", str(tmp_path), "set", "oops"], _context())

    def test_uninstall_keeps_data_and_settings(self, tmp_path, capsys):
        self._installed(tmp_path)
        docker = FakeDocker()
        assert _run(["uninstall", "--yes", "--dir", str(tmp_path)], _context(docker, installer=lambda: "uv")) == 0
        assert docker.calls == [(tmp_path, [*EVERY_PROFILE, "down", "--remove-orphans"])]
        assert (tmp_path / ".env").is_file(), "the database password lives there"
        assert not (tmp_path / "docker-compose.yaml").exists()
        assert not (tmp_path / "install.json").exists()
        assert "uv tool uninstall docsgpt" in capsys.readouterr().out

    def test_uninstall_purge_removes_everything(self, tmp_path):
        directory = tmp_path / "stack"
        self._installed(directory)
        docker = FakeDocker()
        assert _run(["uninstall", "--yes", "--purge", "--dir", str(directory)], _context(docker)) == 0
        assert docker.calls == [(directory, [*EVERY_PROFILE, "down", "--remove-orphans", "-v"])]
        assert not directory.exists()

    def test_uninstall_asks_first(self, tmp_path):
        self._installed(tmp_path)
        docker = FakeDocker()
        prompter = FakePrompter([False])
        assert _run(["uninstall", "--dir", str(tmp_path)], _context(docker, prompter, interactive=True)) == 1
        assert docker.calls == []


class TestUpgrade:
    def test_a_uv_tool_install_upgrades_and_runs_up_again(self, tmp_path):
        self_calls = []
        context = _context(
            installer=lambda: "uv",
            run=lambda args: self_calls.append(args) or 0,
            exec_up=lambda argv: self_calls.append(["exec", *argv]) or 0,
        )
        assert _run(["upgrade", "--dir", str(tmp_path), "--version", "0.22.0"], context) == 0
        assert self_calls[0] == ["uv", "tool", "install", "--force", "docsgpt==0.22.0"]
        assert self_calls[1] == ["exec", "docsgpt", "up", "--dir", str(tmp_path)]

    def test_latest_when_no_version_is_given(self, tmp_path):
        self_calls = []
        context = _context(installer=lambda: "uv", run=lambda args: self_calls.append(args) or 0,
                           exec_up=lambda argv: 0)
        assert _run(["upgrade", "--dir", str(tmp_path)], context) == 0
        assert self_calls[0] == ["uv", "tool", "install", "--force", "docsgpt"]

    def test_a_pip_install_is_told_what_to_run(self, tmp_path, capsys):
        context = _context(installer=lambda: "pip", run=lambda args: pytest.fail("must not run"))
        assert _run(["upgrade", "--dir", str(tmp_path)], context) == 1
        err = capsys.readouterr().err
        assert "pip install -U docsgpt" in err and "docsgpt up" in err


class TestImports:
    def test_the_deploy_commands_do_not_boot_the_app(self):
        code = (
            "import sys, docsgpt.cli, docsgpt.deploy.commands; "
            "loaded = {m for m in sys.modules if m in ('docsgpt.app', 'docsgpt.core.settings', 'celery', 'flask')}; "
            "assert not loaded, loaded"
        )
        subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], check=True)
