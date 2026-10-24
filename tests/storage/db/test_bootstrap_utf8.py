"""``_run_migrations`` must not read ``alembic.ini`` with the OS default encoding.

``docsgpt/alembic.ini`` is UTF-8 — it carries non-ASCII characters — and its
``script_location`` interpolates ``%(here)s``. The old
``Config(str(alembic_ini))`` let alembic read the file with the locale
encoding (``encoding="locale"``: GBK on Chinese Windows), which raises
``UnicodeDecodeError`` while the config is being built, before any migration
can run. The fixed code sets ``here`` on a bare ``Config()`` and reads the
ini itself with ``encoding="utf-8"``.

These tests simulate a GBK machine on any platform by wrapping
``builtins.open`` and ``configparser.ConfigParser.read`` so that a read
without an explicit encoding — and alembic's ``encoding="locale"`` — is
forced to GBK before reaching the real implementation. The wrapper patches
the ``ConfigParser`` class itself, so it also covers alembic's internal
parser, wherever that read happens.

Nothing connects to a database: the alembic script directory and the
``upgrade`` command are stubbed, and the ini points at an in-memory SQLite
URL, so the real ``_run_migrations`` runs to completion without touching
Postgres, the filesystem outside ``tmp_path``, or the network.
"""

from __future__ import annotations

import builtins
import configparser
import logging
from types import SimpleNamespace

import pytest

import docsgpt.storage.db.bootstrap as bootstrap


def _force_gbk_default_encoding(monkeypatch):
    """Simulate a machine whose default and locale encodings are GBK.

    Wraps ``builtins.open`` (a text-mode call without an explicit
    ``encoding``) and ``configparser.ConfigParser.read`` (no encoding, and
    alembic's explicit ``encoding="locale"``), delegating to the real
    implementations with GBK substituted. Reads that pass a real codec —
    like the fixed ``encoding="utf-8"`` — are untouched, so a green test
    proves the production code opts out of the OS default rather than that
    the simulation is disabled.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    real_open = builtins.open

    def gbk_default_open(file, mode="r", buffering=-1, encoding=None, *args, **kwargs):
        if encoding is None and "b" not in mode:
            encoding = "gbk"
        return real_open(file, mode, buffering, encoding, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", gbk_default_open)

    real_read = configparser.ConfigParser.read

    def gbk_default_read(self, filenames, encoding=None):
        # alembic >= 1.20 reads its ini with encoding="locale"; on the
        # simulated machine the locale encoding is GBK.
        if encoding is None or encoding == "locale":
            encoding = "gbk"
        return real_read(self, filenames, encoding=encoding)

    monkeypatch.setattr(configparser.ConfigParser, "read", gbk_default_read)


@pytest.fixture
def migration_env(tmp_path, monkeypatch):
    """A throwaway ``docsgpt`` tree that drives ``_run_migrations`` off tmp_path.

    Builds ``<tmp>/docsgpt/alembic.ini`` and repoints the module's
    ``__file__`` at ``<tmp>/docsgpt/storage/db/bootstrap.py`` so
    ``parents[2]`` resolves to the temp package root, exactly as the real
    module resolves the repo's ``docsgpt/alembic.ini``.

    Returns:
        ``(ini_path, captured)`` — the fixture ini path and the dict the
        stubs record the alembic ``Config`` into.
    """
    package_root = tmp_path / "docsgpt"
    db_dir = package_root / "storage" / "db"
    db_dir.mkdir(parents=True)

    ini_path = package_root / "alembic.ini"
    # Comment lines end in non-ASCII characters, so an encoding-less read is
    # guaranteed to fail rather than quietly mojibake.
    ini_path.write_text(
        "# DocsGPT 迁移配置 —— 本文件按 UTF-8 编码保存\n"
        "[alembic]\n"
        "script_location = %(here)s/alembic\n"
        "prepend_sys_path = %(here)s\n"
        "sqlalchemy.url = sqlite://\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(bootstrap, "__file__", str(db_dir / "bootstrap.py"))

    captured: dict = {}

    def fake_from_config(cfg):
        captured["cfg"] = cfg
        return SimpleNamespace(get_current_head=lambda: "0001_head")

    monkeypatch.setattr("alembic.script.ScriptDirectory.from_config", fake_from_config)

    def record_upgrade(cfg, revision):
        captured["upgrade"] = (cfg, revision)

    monkeypatch.setattr("alembic.command.upgrade", record_upgrade)
    return ini_path, captured


@pytest.mark.unit
class TestRunMigrationsUtf8:
    def test_builds_the_config_as_utf8_on_a_gbk_machine(self, migration_env, monkeypatch):
        """The real config build survives a GBK default and reads real values.

        With the old ``Config(str(alembic_ini))``, alembic read the ini with
        the locale encoding and raised ``UnicodeDecodeError`` before anything
        else could happen.
        """
        _, captured = migration_env
        _force_gbk_default_encoding(monkeypatch)

        bootstrap._run_migrations(logging.getLogger(__name__))

        cfg = captured["cfg"]
        assert cfg.get_main_option("sqlalchemy.url") == "sqlite://"
        # The upgrade step is reached with the fully built config and the
        # head target — it never runs for real (it is stubbed above).
        assert captured["upgrade"][0] is cfg
        assert captured["upgrade"][1] == "head"

    def test_sets_here_so_here_interpolations_resolve_to_the_package(self, migration_env, monkeypatch):
        """``here`` is defined and ini ``%(here)s`` references resolve against it.

        A bare ``Config()`` leaves ``here`` at ``.``; the fixed bootstrap
        points it at the ini's directory before reading it, which is what
        ``script_location = %(here)s/alembic`` interpolates against.
        """
        ini_path, captured = migration_env
        _force_gbk_default_encoding(monkeypatch)

        bootstrap._run_migrations(logging.getLogger(__name__))

        cfg = captured["cfg"]
        here = ini_path.parent.as_posix()
        assert cfg.file_config["DEFAULT"]["here"] == here
        # An option the bootstrap does not override: the raw ini value still
        # holds ``%(here)s``, so reading it exercises the interpolation.
        assert cfg.file_config.get("alembic", "prepend_sys_path") == here
        assert cfg.get_main_option("script_location") == str(ini_path.parent / "alembic")

    def test_the_simulation_breaks_an_encoding_less_read_of_this_ini(self, migration_env, monkeypatch):
        """Control: the fixture ini genuinely fails a locale read on the simulated machine.

        Without this, the tests above could stay green with the
        ``encoding="utf-8"`` argument removed if the ini happened to be
        ASCII-only. Alembic's own ``Config(str(path))`` read — what the old
        code did — fails the same way.
        """
        ini_path, _ = migration_env
        _force_gbk_default_encoding(monkeypatch)

        with pytest.raises(UnicodeDecodeError):
            with open(ini_path, "r") as fh:
                fh.read()

        with pytest.raises(UnicodeDecodeError):
            configparser.ConfigParser().read(ini_path)

        from alembic.config import Config

        with pytest.raises(UnicodeDecodeError):
            cfg = Config(str(ini_path))
            cfg.get_main_option("sqlalchemy.url")
