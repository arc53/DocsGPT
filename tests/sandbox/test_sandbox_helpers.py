"""Argument handling of the conversion helpers baked into the sandbox image.

``office-convert`` (LibreOffice) and ``html-to-pdf`` / ``html-screenshot``
(headless Chromium) live under ``deployment/sandbox/helpers`` and are copied
onto PATH in the image. These tests load them by path and stub the converter
process; the container smoke test (``deployment/sandbox/smoke_test.py``) runs
the real conversions.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import List

import pytest

_HELPERS = Path(__file__).resolve().parents[2] / "deployment" / "sandbox" / "helpers"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_sandbox_helper_{name}", _HELPERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def office():
    return _load("office_convert")


@pytest.fixture
def html():
    return _load("html_render")


class _FakeRun:
    """Stand-in for the helper's process runner: records the command and fakes the converter's effect."""

    def __init__(self, effect=None, returncode: int = 0, stderr: str = "", timeout: bool = False):
        self.calls: List[List[str]] = []
        self.timeouts: List[float] = []
        self.effect = effect
        self.returncode = returncode
        self.stderr = stderr
        self.timeout = timeout

    def __call__(self, cmd, timeout):
        self.calls.append(list(cmd))
        self.timeouts.append(timeout)
        if self.timeout:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if self.effect:
            self.effect(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


# -- office-convert ------------------------------------------------------------


def test_office_convert_defaults_to_pdf_in_the_current_directory(office, tmp_path, monkeypatch, capsys):
    src = tmp_path / "inputs" / "report.docx"
    src.parent.mkdir()
    src.write_bytes(b"docx")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(office, "find_soffice", lambda: "/usr/bin/soffice")

    def effect(cmd):
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        (outdir / "report.pdf").write_bytes(b"%PDF-1.7")

    fake = _FakeRun(effect)
    monkeypatch.setattr(office, "run", fake)

    assert office.main([str(src)]) == 0
    cmd = fake.calls[0]
    assert cmd[0] == "/usr/bin/soffice"
    assert "--headless" in cmd
    assert cmd[cmd.index("--convert-to") + 1] == "pdf"
    assert Path(cmd[cmd.index("--outdir") + 1]) == tmp_path
    assert cmd[-1] == str(src.resolve())
    assert capsys.readouterr().out.strip() == str(tmp_path / "report.pdf")


def test_office_convert_uses_a_fresh_profile_per_call_and_removes_it(office, tmp_path, monkeypatch):
    """A shared LibreOffice profile makes a second soffice exit 0 having written nothing."""
    src = tmp_path / "a.pptx"
    src.write_bytes(b"pptx")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    profiles = []

    def effect(cmd):
        flag = next(c for c in cmd if c.startswith("-env:UserInstallation=file://"))
        profile = Path(flag.split("file://", 1)[1])
        assert profile.is_dir()
        profiles.append(profile)
        (tmp_path / "a.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(office, "run", _FakeRun(effect))
    assert office.main([str(src), "--outdir", str(tmp_path)]) == 0
    (tmp_path / "a.pdf").unlink()
    assert office.main([str(src), "--outdir", str(tmp_path)]) == 0
    assert len(profiles) == 2 and profiles[0] != profiles[1]
    assert not any(p.exists() for p in profiles)


@pytest.mark.parametrize(
    "fmt,filter_arg,ext",
    [
        ("docx", "docx:MS Word 2007 XML", "docx"),
        ("xlsx", "xlsx:Calc MS Excel 2007 XML", "xlsx"),
        ("pptx", "pptx:Impress MS PowerPoint 2007 XML", "pptx"),
        ("png", "png", "png"),
    ],
)
def test_office_convert_maps_each_format_to_a_filter(office, tmp_path, monkeypatch, fmt, filter_arg, ext):
    src = tmp_path / "deck.odp"
    src.write_bytes(b"x")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    fake = _FakeRun(lambda cmd: (tmp_path / "out" / f"deck.{ext}").write_bytes(b"data"))
    monkeypatch.setattr(office, "run", fake)
    assert office.main([str(src), "--to", fmt, "--outdir", str(tmp_path / "out")]) == 0
    assert fake.calls[0][fake.calls[0].index("--convert-to") + 1] == filter_arg
    assert (tmp_path / "out").is_dir()


def test_office_convert_fails_loudly_when_soffice_writes_nothing(office, tmp_path, monkeypatch, capsys):
    """soffice exits 0 without output when it cannot convert; the helper must not report success."""
    src = tmp_path / "broken.docx"
    src.write_bytes(b"not really a docx")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(office, "run", _FakeRun(stderr="Error: source file could not be loaded"))
    assert office.main([str(src), "--outdir", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "no output" in err and "broken.pdf" in err
    assert "source file could not be loaded" in err


def test_office_convert_does_not_count_a_stale_output_as_success(office, tmp_path, monkeypatch):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    (tmp_path / "r.pdf").write_bytes(b"%PDF old")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(office, "run", _FakeRun())
    assert office.main([str(src), "--outdir", str(tmp_path)]) == 1


def test_office_convert_reports_a_converter_error(office, tmp_path, monkeypatch, capsys):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    monkeypatch.setattr(office, "run", _FakeRun(returncode=81, stderr="boom"))
    assert office.main([str(src)]) == 1
    assert "exited with 81" in capsys.readouterr().err


def test_office_convert_times_out_cleanly(office, tmp_path, monkeypatch, capsys):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    fake = _FakeRun(timeout=True)
    monkeypatch.setattr(office, "run", fake)
    assert office.main([str(src), "--timeout", "7"]) == 124
    assert fake.timeouts == [7.0]
    assert "timed out after 7" in capsys.readouterr().err


def test_office_convert_rejects_a_missing_input(office, tmp_path, capsys):
    assert office.main([str(tmp_path / "nope.docx")]) == 2
    assert "not found" in capsys.readouterr().err


def test_office_convert_refuses_to_overwrite_its_input(office, tmp_path, monkeypatch, capsys):
    src = tmp_path / "same.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(office, "find_soffice", lambda: "soffice")
    assert office.main([str(src), "--to", "docx", "--outdir", str(tmp_path)]) == 2
    assert "overwrite" in capsys.readouterr().err


def test_office_convert_rejects_an_unknown_format(office, tmp_path):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        office.main([str(src), "--to", "exe"])
    assert exc.value.code == 2


def test_office_convert_rejects_a_non_positive_timeout(office, tmp_path):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    with pytest.raises(SystemExit) as exc:
        office.main([str(src), "--timeout", "0"])
    assert exc.value.code == 2


def test_office_convert_without_libreoffice(office, tmp_path, monkeypatch, capsys):
    src = tmp_path / "r.docx"
    src.write_bytes(b"x")
    monkeypatch.setattr(office, "find_soffice", lambda: None)
    assert office.main([str(src)]) == 127
    assert "LibreOffice" in capsys.readouterr().err


def test_office_convert_run_kills_the_whole_process_group_on_timeout(office):
    """soffice forks soffice.bin; a timeout must not leave it running."""
    with pytest.raises(subprocess.TimeoutExpired):
        office.run(["sh", "-c", "sleep 30 & sleep 30"], timeout=0.5)


def test_office_convert_run_returns_the_process_result(office):
    result = office.run(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10)
    assert result.returncode == 3
    assert result.stdout.strip() == "out"
    assert result.stderr.strip() == "err"


# -- html-to-pdf / html-screenshot ---------------------------------------------


def test_to_url_turns_a_local_file_into_an_absolute_file_url(html, tmp_path, monkeypatch):
    page = tmp_path / "page one.html"
    page.write_text("<p>x</p>")
    monkeypatch.chdir(tmp_path)
    assert html.to_url("page one.html") == page.resolve().as_uri()


@pytest.mark.parametrize("url", ["https://example.com/a", "http://example.com", "file:///tmp/x.html"])
def test_to_url_passes_urls_through(html, url):
    assert html.to_url(url) == url


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://example.com/x", "missing.html"])
def test_to_url_rejects_other_schemes_and_missing_files(html, bad, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        html.to_url(bad)


def test_find_browser_prefers_the_headless_shell(html, monkeypatch):
    available = {"chromium": "/usr/bin/chromium", "chromium-headless-shell": "/usr/bin/chromium-headless-shell"}
    monkeypatch.setattr(html.shutil, "which", available.get)
    assert html.find_browser() == "/usr/bin/chromium-headless-shell"
    available.pop("chromium-headless-shell")
    assert html.find_browser() == "/usr/bin/chromium"
    available.clear()
    assert html.find_browser() is None


def _browser_effect(cmd):
    for arg in cmd:
        for flag in ("--print-to-pdf=", "--screenshot="):
            if arg.startswith(flag):
                Path(arg[len(flag):]).write_bytes(b"out")


def test_html_to_pdf_command(html, tmp_path, monkeypatch, capsys):
    page = tmp_path / "in.html"
    page.write_text("<h1>hi</h1>")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "/usr/bin/chromium-headless-shell")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)

    assert html.main(["in.html", "out.pdf"], prog="html-to-pdf") == 0
    cmd = fake.calls[0]
    assert cmd[0] == "/usr/bin/chromium-headless-shell"
    for flag in ("--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-pdf-header-footer"):
        assert flag in cmd
    assert f"--print-to-pdf={tmp_path / 'out.pdf'}" in cmd
    assert any(c.startswith("--user-data-dir=") for c in cmd)
    assert cmd[-1] == page.resolve().as_uri()
    assert capsys.readouterr().out.strip() == str(tmp_path / "out.pdf")


def test_html_screenshot_command_sets_the_window_size(html, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)
    url = "https://example.com"
    assert html.main([url, "shot.png", "--width", "800", "--height", "600"], prog="html-screenshot") == 0
    cmd = fake.calls[0]
    assert f"--screenshot={tmp_path / 'shot.png'}" in cmd
    assert "--window-size=800,600" in cmd
    assert "--hide-scrollbars" in cmd
    assert cmd[-1] == url


def test_html_screenshot_defaults_to_a_desktop_viewport(html, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)
    assert html.main(["https://example.com", "s.png"], prog="html-screenshot") == 0
    assert "--window-size=1280,800" in fake.calls[0]


def test_html_render_removes_the_browser_profile(html, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)
    assert html.main(["https://example.com", "o.pdf"], prog="html-to-pdf") == 0
    profile = next(c for c in fake.calls[0] if c.startswith("--user-data-dir=")).split("=", 1)[1]
    assert not Path(profile).exists()


def test_html_render_passes_the_wait_budget(html, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)
    assert html.main(["https://example.com", "o.pdf", "--wait-ms", "0"], prog="html-to-pdf") == 0
    assert not any(c.startswith("--virtual-time-budget") for c in fake.calls[0])
    assert html.main(["https://example.com", "o.pdf", "--wait-ms", "1500"], prog="html-to-pdf") == 0
    assert "--virtual-time-budget=1500" in fake.calls[1]


def test_html_render_fails_when_no_file_appears(html, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    monkeypatch.setattr(html, "run", _FakeRun(stderr="net::ERR_NAME_NOT_RESOLVED"))
    assert html.main(["https://nope.invalid", "o.pdf"], prog="html-to-pdf") == 1
    err = capsys.readouterr().err
    assert "no output" in err and "ERR_NAME_NOT_RESOLVED" in err


def test_html_render_reports_a_browser_error(html, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    monkeypatch.setattr(html, "run", _FakeRun(returncode=1, stderr="crash"))
    assert html.main(["https://example.com", "o.pdf"], prog="html-to-pdf") == 1
    assert "exited with 1" in capsys.readouterr().err


def test_html_render_times_out_cleanly(html, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    monkeypatch.setattr(html, "run", _FakeRun(timeout=True))
    assert html.main(["https://example.com", "o.pdf", "--timeout", "5"], prog="html-to-pdf") == 124
    assert "timed out after 5" in capsys.readouterr().err


def test_html_render_without_a_browser(html, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: None)
    assert html.main(["https://example.com", "o.pdf"], prog="html-to-pdf") == 127
    assert "Chromium" in capsys.readouterr().err


def test_html_render_rejects_a_bad_input(html, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    assert html.main(["missing.html", "o.pdf"], prog="html-to-pdf") == 2
    assert "not found" in capsys.readouterr().err


@pytest.mark.parametrize("args", [["--width", "0"], ["--height", "-5"], ["--width", "abc"]])
def test_html_screenshot_rejects_bad_sizes(html, args):
    with pytest.raises(SystemExit) as exc:
        html.main(["https://example.com", "s.png", *args], prog="html-screenshot")
    assert exc.value.code == 2


def test_html_render_needs_a_known_command_name(html, capsys):
    assert html.main(["a", "b"], prog="html_render.py") == 2
    assert "html-to-pdf" in capsys.readouterr().err


def test_html_render_takes_its_mode_from_the_command_name(html, monkeypatch):
    seen = {}
    monkeypatch.setattr(html, "_render", lambda mode, prog, argv: seen.setdefault("mode", mode) and 0)
    monkeypatch.setattr(html.sys, "argv", ["/usr/local/bin/html-screenshot", "https://example.com", "s.png"])
    html.main()
    assert seen["mode"] == "screenshot"


@pytest.mark.parametrize("as_url", [False, True])
def test_html_render_refuses_to_overwrite_its_input(html, tmp_path, monkeypatch, capsys, as_url):
    """``html-to-pdf page.html page.html`` must not delete the page before rendering it."""
    page = tmp_path / "page.html"
    page.write_text("<p>keep me</p>")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(html, "find_browser", lambda: "chromium")
    fake = _FakeRun(_browser_effect)
    monkeypatch.setattr(html, "run", fake)
    target = page.resolve().as_uri() if as_url else "page.html"
    assert html.main([target, str(page)], prog="html-to-pdf") == 2
    assert "overwrite" in capsys.readouterr().err
    assert page.read_text() == "<p>keep me</p>"
    assert fake.calls == []
