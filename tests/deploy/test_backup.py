"""`docsgpt backup` and `docsgpt restore`, against a fake Docker."""

import io
import json
import stat
import tarfile
from pathlib import Path

import pytest

from docsgpt.deploy import backup as backup_module
from docsgpt.deploy.docker import DeployError

from .test_commands import FakeDocker, FakePrompter, _context, _run


def _installed(tmp_path, *extra):
    assert _run(["up", "--yes", "--dir", str(tmp_path), *extra], _context()) == 0


def _archive_names(path):
    with tarfile.open(path, "r:gz") as archive:
        return sorted(member.name for member in archive.getmembers() if member.isfile())


def _manifest(path):
    with tarfile.open(path, "r:gz") as archive:
        return json.loads(archive.extractfile(backup_module.MANIFEST).read())


def _rewrite(archive, dest, *, volumes=None, drop=(), corrupt=()):
    """The same archive with other volumes in its manifest, or with members left out or damaged."""
    with tarfile.open(archive, "r:gz") as source, tarfile.open(dest, "w:gz") as out:
        for member in source.getmembers():
            if member.name in drop:
                continue
            body = source.extractfile(member).read() if member.isfile() else None
            if member.name in corrupt:
                body = body[:60]
                member.size = len(body)
            if member.name == backup_module.MANIFEST and volumes is not None:
                manifest = json.loads(body.decode())
                manifest["volumes"] = volumes
                body = json.dumps(manifest).encode()
                member.size = len(body)
            out.addfile(member, io.BytesIO(body) if body is not None else None)
    return dest


def _copy_with_version(archive, version, dest):
    """The same archive, with another DocsGPT version written into its manifest."""
    with tarfile.open(archive, "r:gz") as source, tarfile.open(dest, "w:gz") as out:
        for member in source.getmembers():
            body = source.extractfile(member).read() if member.isfile() else None
            if member.name == backup_module.MANIFEST:
                manifest = json.loads(body.decode())
                manifest["version"] = version
                body = json.dumps(manifest).encode()
                member.size = len(body)
            out.addfile(member, io.BytesIO(body) if body is not None else None)
    return dest


class TestBackup:
    def test_writes_a_dump_a_tar_per_volume_and_a_manifest(self, tmp_path, capsys):
        _installed(tmp_path)
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        out = tmp_path / "backups"
        assert _run(["backup", "--dir", str(tmp_path), "--out", str(out)], _context(docker)) == 0

        archives = list(out.glob("docsgpt-*.tar.gz"))
        assert len(archives) == 1, archives
        names = _archive_names(archives[0])
        assert backup_module.DUMP in names
        for volume in ("indexes", "inputs", "vectors"):
            assert f"volumes/{volume}.tar" in names
        manifest = _manifest(archives[0])
        assert manifest["version"] == "0.21.0"
        assert manifest["image_tag"] == "0.21.0"
        assert manifest["volumes"] == ["indexes", "inputs", "vectors"]
        assert manifest["settings_included"] is False
        assert "Backup written to" in capsys.readouterr().out
        assert [op for op in docker.volume_ops if op[0] == "export"], docker.volume_ops

    def test_the_settings_file_is_left_out_unless_asked_for(self, tmp_path):
        _installed(tmp_path)
        out = tmp_path / "backups"
        assert _run(["backup", "--dir", str(tmp_path), "--out", str(out)], _context()) == 0
        assert backup_module.SETTINGS not in _archive_names(next(out.glob("*.tar.gz")))

        with_settings = tmp_path / "with-settings"
        argv = ["backup", "--dir", str(tmp_path), "--out", str(with_settings), "--with-settings"]
        assert _run(argv, _context()) == 0
        assert backup_module.SETTINGS in _archive_names(next(with_settings.glob("*.tar.gz")))

    def test_the_database_is_dumped_from_the_running_container(self, tmp_path):
        _installed(tmp_path)
        docker = FakeDocker()
        assert _run(["backup", "--dir", str(tmp_path), "--out", str(tmp_path / "b")], _context(docker)) == 0
        dumps = [args for _, args in docker.calls if "pg_dump" in " ".join(args)]
        assert dumps, docker.calls
        assert dumps[0][:3] == ["exec", "-T", "postgres"]

    def test_the_archive_is_private_to_whoever_took_it(self, tmp_path):
        """It can hold .env, and the dump is the install's data either way."""
        _installed(tmp_path)
        out = tmp_path / "backups"
        argv = ["backup", "--dir", str(tmp_path), "--out", str(out), "--with-settings"]
        assert _run(argv, _context()) == 0
        archive = next(out.glob("*.tar.gz"))
        assert stat.S_IMODE(archive.stat().st_mode) == 0o600

    def test_the_writers_are_stopped_while_the_archive_is_made(self, tmp_path):
        """Ingestion writes files and rows; a dump taken alongside live writes would not match them."""
        _installed(tmp_path)
        docker = FakeDocker()
        assert _run(["backup", "--dir", str(tmp_path), "--out", str(tmp_path / "b")], _context(docker)) == 0
        joined = [" ".join(args) for _, args in docker.calls]
        stopped = next(index for index, call in enumerate(joined) if call.startswith("stop backend worker"))
        dumped = next(index for index, call in enumerate(joined) if "pg_dump" in call)
        started = next(index for index, call in enumerate(joined) if call.startswith("up -d backend worker"))
        assert stopped < dumped < started, joined

    def test_the_writers_come_back_even_when_stopping_them_fails(self, tmp_path):
        """A stop that fails partway must not leave the backend or the worker down."""
        _installed(tmp_path)

        class FailingStop(FakeDocker):
            def compose(self, directory, *args, **kwargs):
                if args[:1] == ("stop",):
                    self.calls.append((Path(directory), list(args)))
                    raise DeployError("compose stop exploded")
                return super().compose(directory, *args, **kwargs)

        docker = FailingStop()
        with pytest.raises(DeployError, match="compose stop exploded"):
            _run(["backup", "--dir", str(tmp_path), "--out", str(tmp_path / "b")], _context(docker))
        assert any(" ".join(args).startswith("up -d backend worker") for _, args in docker.calls), docker.calls

    def test_the_writers_come_back_even_when_the_dump_fails(self, tmp_path):
        _installed(tmp_path)

        class FailingDump(FakeDocker):
            def compose(self, directory, *args, **kwargs):
                if "pg_dump" in args:
                    raise DeployError("pg_dump exploded")
                return super().compose(directory, *args, **kwargs)

        docker = FailingDump()
        with pytest.raises(DeployError, match="pg_dump exploded"):
            _run(["backup", "--dir", str(tmp_path), "--out", str(tmp_path / "b")], _context(docker))
        assert any(" ".join(args).startswith("up -d backend worker") for _, args in docker.calls), docker.calls

    def test_without_an_install(self, tmp_path, capsys):
        assert _run(["backup", "--dir", str(tmp_path)], _context()) == 1
        assert "docsgpt up" in capsys.readouterr().err


class TestRestore:
    def _backup(self, tmp_path, *extra):
        _installed(tmp_path)
        out = tmp_path / "backups"
        assert _run(["backup", "--dir", str(tmp_path), "--out", str(out), *extra], _context()) == 0
        return next(out.glob("*.tar.gz"))

    def test_restores_the_volumes_and_the_database(self, tmp_path):
        archive = self._backup(tmp_path)
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        argv = ["restore", str(archive), "--dir", str(tmp_path), "--yes"]
        assert _run(argv, _context(docker)) == 0
        joined = [" ".join(args) for _, args in docker.calls]
        assert any(call.startswith("--profile https down") for call in joined), joined
        assert any("psql" in call for call in joined), joined
        assert any(call.startswith("up -d") for call in joined), joined

    def test_asks_before_replacing_data(self, tmp_path):
        archive = self._backup(tmp_path)
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        prompter = FakePrompter([False])
        assert _run(["restore", str(archive), "--dir", str(tmp_path)], _context(docker, prompter, interactive=True)) == 1
        assert docker.calls == []

    def test_refuses_an_archive_that_is_not_a_docsgpt_backup(self, tmp_path):
        stray = tmp_path / "stray.tar.gz"
        with tarfile.open(stray, "w:gz") as archive:
            note = tmp_path / "note.txt"
            note.write_text("not a backup")
            archive.add(note, arcname="note.txt")
        with pytest.raises(DeployError, match="not a DocsGPT backup"):
            _run(["restore", str(stray), "--dir", str(tmp_path), "--yes"], _context())

    def test_a_missing_archive(self, tmp_path):
        with pytest.raises(DeployError, match="does not exist"):
            _run(["restore", str(tmp_path / "nope.tar.gz"), "--dir", str(tmp_path), "--yes"], _context())

    def test_a_manifest_naming_another_volume_is_refused(self, tmp_path):
        """import_volume empties what it is given, so a hand-made manifest must not name postgres_data."""
        crafted = _rewrite(self._backup(tmp_path), tmp_path / "crafted.tar.gz", volumes=["postgres_data"])
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        with pytest.raises(DeployError, match="not part of a backup"):
            _run(["restore", str(crafted), "--dir", str(tmp_path), "--yes"], _context(docker))
        assert docker.calls == [], "nothing was stopped"
        assert docker.volume_ops == [], "and nothing was touched"

    def test_a_damaged_archive_fails_before_the_stack_is_stopped(self, tmp_path):
        """Discovering a missing member after `compose down` would leave DocsGPT down for nothing."""
        without_dump = _rewrite(self._backup(tmp_path), tmp_path / "nodump.tar.gz", drop=(backup_module.DUMP,))
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        with pytest.raises(DeployError, match="nothing to restore"):
            _run(["restore", str(without_dump), "--dir", str(tmp_path), "--yes"], _context(docker))
        assert docker.calls == [], "DocsGPT is still running"

    def test_psql_stops_at_the_first_failing_statement(self, tmp_path):
        """Without it psql runs on after an error and a half-restored database looks like success."""
        archive = self._backup(tmp_path)
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        assert _run(["restore", str(archive), "--dir", str(tmp_path), "--yes"], _context(docker)) == 0
        psql = next(args for _, args in docker.calls if "psql" in args)
        assert "ON_ERROR_STOP=on" in psql

    def test_a_failure_after_the_stack_is_down_starts_it_again(self, tmp_path, capsys):
        """A corrupt payload only shows up once the stack is down; it must not be left stopped."""
        archive = self._backup(tmp_path)

        class FailingImport(FakeDocker):
            def import_volume(self, volume, source, image):
                raise DeployError("tar: unexpected EOF in archive")

        docker = FailingImport(volumes={"docsgpt_postgres_data"})
        with pytest.raises(DeployError, match="unexpected EOF"):
            _run(["restore", str(archive), "--dir", str(tmp_path), "--yes"], _context(docker))
        joined = [" ".join(args) for _, args in docker.calls]
        assert any(call.startswith("up -d --remove-orphans") for call in joined), joined
        assert "Starting DocsGPT again" in capsys.readouterr().err

    def test_a_shutdown_that_fails_still_starts_the_stack_again(self, tmp_path):
        """`compose down` can fail with containers already stopped; the stack must not stay down."""
        archive = self._backup(tmp_path)

        class FailingDown(FakeDocker):
            def compose(self, directory, *args, **kwargs):
                if "down" in args:
                    self.calls.append((Path(directory), list(args)))
                    raise DeployError("compose down exploded")
                return super().compose(directory, *args, **kwargs)

        docker = FailingDown(volumes={"docsgpt_postgres_data"})
        with pytest.raises(DeployError, match="compose down exploded"):
            _run(["restore", str(archive), "--dir", str(tmp_path), "--yes"], _context(docker))
        joined = [" ".join(args) for _, args in docker.calls]
        assert any(call.startswith("up -d --remove-orphans") for call in joined), joined

    def test_a_damaged_volume_tar_is_found_before_any_volume_is_replaced(self, tmp_path):
        """vectors sorts last, so a per-volume check would already have swapped indexes and inputs."""
        archive = _rewrite(self._backup(tmp_path), tmp_path / "bad-volume.tar.gz",
                           corrupt=(backup_module.volume_member("vectors"),))
        docker = FakeDocker(volumes={"docsgpt_postgres_data"})
        with pytest.raises(DeployError, match="damaged"):
            _run(["restore", str(archive), "--dir", str(tmp_path), "--yes"], _context(docker))
        assert [op for op in docker.volume_ops if op[0] == "import"] == [], docker.volume_ops

    def test_a_newer_backup_is_refused_without_force(self, tmp_path):
        """Restoring a 0.22 backup into 0.21 would hand an older schema newer data."""
        newer = _copy_with_version(self._backup(tmp_path), "0.22.0", tmp_path / "newer.tar.gz")
        with pytest.raises(DeployError, match="newer"):
            _run(["restore", str(newer), "--dir", str(tmp_path), "--yes"], _context(FakeDocker()))
        argv = ["restore", str(newer), "--dir", str(tmp_path), "--yes", "--force"]
        assert _run(argv, _context(FakeDocker())) == 0
