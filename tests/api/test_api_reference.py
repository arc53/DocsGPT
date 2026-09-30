"""The REST API reference snapshot the docs site renders (docsgpt/api/reference.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docsgpt.api.reference import build_spec, main, render_spec, snapshot_path

METHODS = ("get", "put", "post", "delete", "patch", "head", "options")


def _operations(spec):
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method in METHODS:
                yield path, method, operation


@pytest.mark.unit
class TestSnapshot:
    def test_is_the_swagger_document(self):
        spec = build_spec()
        assert spec["swagger"] == "2.0"
        assert spec["info"]["title"] == "DocsGPT API"
        assert "/api/create_agent" in spec["paths"]

    def test_has_no_host_specific_values(self):
        spec = build_spec()
        assert "host" not in spec
        assert spec["basePath"] == "/"

    def test_rendering_is_deterministic(self):
        first = render_spec()
        assert first == render_spec()
        assert first.endswith("\n")
        assert json.loads(first) == build_spec()

    def test_every_operation_says_how_a_token_may_call_it(self):
        missing = [
            f"{method.upper()} {path}"
            for path, method, operation in _operations(build_spec())
            if "x-pat-scopes" not in operation and not operation.get("x-pat-denied")
        ]
        assert not missing

    def test_scoped_operation_names_its_scope(self):
        operation = build_spec()["paths"]["/api/create_agent"]["post"]
        assert operation["x-pat-scopes"] == ["agents:write"]
        assert "x-pat-denied" not in operation

    def test_path_parameters_are_matched_to_the_rule_table(self):
        operation = build_spec()["paths"]["/api/teams/{team_id}"]["get"]
        assert operation["x-pat-scopes"] == ["teams:read"]

    def test_token_management_is_denied(self):
        paths = build_spec()["paths"]
        assert paths["/api/user/tokens"]["get"]["x-pat-denied"] is True
        assert "x-pat-scopes" not in paths["/api/user/tokens"]["get"]
        assert paths["/api/admin/users"]["get"]["x-pat-denied"] is True

    def test_checked_in_snapshot_is_current(self):
        path: Path = snapshot_path()
        if not path.parent.parent.is_dir():
            pytest.skip("docs tree not present (installed package, not a checkout)")
        assert path.exists() and path.read_text(encoding="utf-8") == render_spec(), (
            f"{path} is stale; run: python -m docsgpt.api.reference --write"
        )


@pytest.mark.unit
class TestCli:
    def test_check_fails_on_a_stale_snapshot(self, tmp_path, monkeypatch, capsys):
        stale = tmp_path / "swagger.json"
        stale.write_text("{}\n", encoding="utf-8")
        monkeypatch.setattr("docsgpt.api.reference.snapshot_path", lambda: stale)
        assert main(["--check"]) == 1
        assert "--write" in capsys.readouterr().err

    def test_write_then_check_passes(self, tmp_path, monkeypatch):
        target = tmp_path / "swagger.json"
        monkeypatch.setattr("docsgpt.api.reference.snapshot_path", lambda: target)
        assert main(["--write"]) == 0
        assert main(["--check"]) == 0
        assert target.read_text(encoding="utf-8") == render_spec()
