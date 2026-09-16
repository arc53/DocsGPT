"""`docsgpt backup` and `docsgpt restore`, against a fake Docker."""

import io
import json
import tarfile

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

    def test_a_newer_backup_is_refused_without_force(self, tmp_path):
        """Restoring a 0.22 backup into 0.21 would hand an older schema newer data."""
        newer = _copy_with_version(self._backup(tmp_path), "0.22.0", tmp_path / "newer.tar.gz")
        with pytest.raises(DeployError, match="newer"):
            _run(["restore", str(newer), "--dir", str(tmp_path), "--yes"], _context(FakeDocker()))
        argv = ["restore", str(newer), "--dir", str(tmp_path), "--yes", "--force"]
        assert _run(argv, _context(FakeDocker())) == 0
