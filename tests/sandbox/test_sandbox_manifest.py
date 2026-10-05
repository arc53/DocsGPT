"""The sandbox package manifest and the image files generated from it.

``docsgpt/sandbox/manifest.py`` is the single list of what the code sandbox
holds. The Daytona snapshot builds from it directly; the self-hosted runner's
Dockerfile installs from files generated from it, so these tests fail when a
generated file is stale or when the manifest stops describing a reproducible,
checksum-verified image.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from docsgpt.sandbox import manifest

_REPO = Path(__file__).resolve().parents[2]
_SANDBOX_DIR = _REPO / "deployment" / "sandbox"


# -- Generated files -----------------------------------------------------------


@pytest.mark.parametrize("rel_path", sorted(manifest.generated_files()))
def test_generated_file_is_current(rel_path):
    """Every generated file matches the manifest; run scripts/export_sandbox_manifest.py when this fails."""
    expected = manifest.generated_files()[rel_path]
    actual = (_REPO / rel_path).read_text()
    assert actual == expected, f"{rel_path} is stale: run python scripts/export_sandbox_manifest.py"


def test_generated_files_live_in_the_runner_build_context():
    """The runner image builds with deployment/sandbox as its context, so the files must be there."""
    for rel_path in manifest.generated_files():
        assert Path(rel_path).parent == Path("deployment/sandbox")


def test_export_script_check_mode_passes_on_a_clean_tree():
    """CI runs the export script in --check mode; it must agree with the test above."""
    proc = subprocess.run(
        [sys.executable, str(_REPO / "scripts" / "export_sandbox_manifest.py"), "--check"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_export_script_check_mode_reports_a_stale_file(tmp_path):
    """--check fails, naming the file, when a generated file differs."""
    sys.path.insert(0, str(_REPO / "scripts"))
    try:
        import export_sandbox_manifest as export
    finally:
        sys.path.pop(0)
    target = tmp_path / "deployment" / "sandbox"
    target.mkdir(parents=True)
    assert export.main(["--root", str(tmp_path)]) == 0
    for rel_path in manifest.generated_files():
        assert (tmp_path / rel_path).is_file()
    assert export.main(["--root", str(tmp_path), "--check"]) == 0
    (tmp_path / "deployment" / "sandbox" / "requirements.txt").write_text("stale\n")
    assert export.main(["--root", str(tmp_path), "--check"]) == 1


# -- pip -----------------------------------------------------------------------


def test_every_pip_package_is_an_exact_pin_with_an_import_name():
    for pkg in manifest.PIP_PACKAGES + manifest.RUNNER_PIP_PACKAGES:
        assert re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][A-Za-z0-9.]*", pkg["spec"]), pkg
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", pkg["import"]), pkg
        assert pkg["use"].strip(), pkg


def test_pip_packages_have_no_duplicates():
    names = [manifest.dist_name(p["spec"]).lower() for p in manifest.PIP_PACKAGES + manifest.RUNNER_PIP_PACKAGES]
    assert len(names) == len(set(names))


def test_sandbox_carries_the_libraries_models_reach_for():
    """The production misses: requests, pypdf, PyPDF2, bs4, pdfplumber, OCR, animation, YAML."""
    imports = {p["import"] for p in manifest.PIP_PACKAGES}
    assert {
        "pandas",
        "matplotlib",
        "docx",
        "pptx",
        "openpyxl",
        "reportlab",
        "requests",
        "pypdf",
        "PyPDF2",
        "bs4",
        "pdfplumber",
        "pypdfium2",
        "pytesseract",
        "imageio",
        "yaml",
    } <= imports


def test_pillow_stays_below_twelve_so_pdfplumber_is_pinned_to_0_11_9():
    """pdfplumber 0.11.10 needs Pillow >= 12.2; the image keeps Pillow 11.3.0."""
    specs = manifest.pip_specs()
    assert "pillow==11.3.0" in specs
    assert "pdfplumber==0.11.9" in specs
    assert "pdfminer.six==20251230" in specs
    assert "pypdfium2==5.13.0" in specs


def test_agpl_pymupdf_is_never_installed():
    names = {manifest.dist_name(s).lower() for s in manifest.pip_specs(include_runner=True)}
    assert not names & {"pymupdf", "fitz", "pymupdfb"}


def test_runner_only_packages_stay_out_of_the_snapshot():
    """The gateway packages are runner plumbing; Daytona has its own process API."""
    snapshot = manifest.pip_specs()
    runner = manifest.pip_specs(include_runner=True)
    assert not any(s.startswith("jupyter-kernel-gateway") for s in snapshot)
    assert any(s.startswith("jupyter-kernel-gateway") for s in runner)
    assert any(s.startswith("ipykernel") for s in runner)
    assert set(snapshot) < set(runner)


def test_requirements_file_lists_every_runner_pin():
    text = manifest.render_requirements()
    pins = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert pins == list(manifest.pip_specs(include_runner=True))
    assert text.startswith("# GENERATED")


# -- apt, fonts, Node ----------------------------------------------------------


def test_apt_packages_cover_ocr_office_browser_and_fonts():
    names = set(manifest.apt_package_names())
    assert {
        "tesseract-ocr",
        "tesseract-ocr-eng",
        "poppler-utils",
        "libreoffice-writer-nogui",
        "libreoffice-calc-nogui",
        "libreoffice-impress-nogui",
        "chromium-headless-shell",
        "fonts-dejavu-core",
        "fonts-liberation2",
        "fonts-crosextra-carlito",
        "fonts-crosextra-caladea",
        "fonts-noto-core",
        "fonts-noto-cjk",
        "ffmpeg",
    } <= names
    assert len(names) == len(manifest.apt_package_names())


def test_node_is_an_exact_v24_build_with_pinned_checksums():
    node = manifest.NODE
    assert re.fullmatch(r"24\.\d+\.\d+", node["version"])
    assert set(node["sha256"]) == {"amd64", "arm64"}
    for digest in node["sha256"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
    url = manifest.node_url("amd64")
    assert url == f"https://nodejs.org/dist/v{node['version']}/node-v{node['version']}-linux-x64.tar.xz"
    assert manifest.node_url("arm64").endswith("-linux-arm64.tar.xz")
    assert "latest" not in node["url"]


def test_node_url_rejects_an_unpinned_architecture():
    with pytest.raises(ValueError):
        manifest.node_url("riscv64")


def test_system_install_verifies_node_against_the_hardcoded_hash():
    """The build checks the tarball against the manifest hash, never a downloaded SHASUMS file."""
    script = manifest.render_install_system_script()
    for digest in manifest.NODE["sha256"].values():
        assert digest in script
    assert "sha256sum -c" in script
    assert "SHASUMS" not in script
    assert "--strip-components=1" in script
    assert "-C /usr/local" in script


def test_system_install_runs_one_apt_transaction_and_cleans_up():
    commands = manifest.system_install_commands()
    install = [c for c in commands if c.startswith("apt-get install")]
    assert len(install) == 1
    assert "--no-install-recommends" in install[0]
    for name in manifest.apt_package_names():
        assert f" {name}" in install[0]
    assert commands.index("apt-get update") < commands.index(install[0])
    assert "rm -rf /var/lib/apt/lists/*" in commands
    assert "fc-cache -f" in commands
    # Fonts are cached after every font package (and the compat link) is in place.
    assert commands.index("fc-cache -f") > commands.index(install[0])


def test_install_script_is_valid_sh_and_stops_on_errors():
    script = manifest.render_install_system_script()
    assert script.startswith("#!/bin/sh\n")
    assert "set -eu" in script
    proc = subprocess.run(["sh", "-n"], input=script, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_one_line_install_matches_the_script():
    """Daytona runs the same commands as one RUN line; nothing is dropped in the join."""
    line = manifest.install_system_one_liner()
    assert "\n" not in line
    for command in manifest.system_install_commands():
        assert command in line
    proc = subprocess.run(["sh", "-n", "-c", line], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_fonts_name_scripts_and_a_path_under_the_font_dirs():
    assert manifest.FONTS
    for font in manifest.FONTS:
        assert font["name"] and font["scripts"]
        assert font["path"].startswith("/usr/share/fonts/")
    paths = {f["path"] for f in manifest.FONTS}
    assert "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf" in paths
    covered = " ".join(f["scripts"] for f in manifest.FONTS)
    for script in ("Latin", "Arabic", "Devanagari", "Chinese", "Japanese"):
        assert script in covered


def test_pdf_fonts_start_with_the_base_family_and_come_from_installed_packages():
    fonts = manifest.PDF_FONTS
    assert fonts[0]["script"] == "base"
    assert fonts[0]["regular"] == "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    packages = {"dejavu": "fonts-dejavu-core", "noto": "fonts-noto-core"}
    for font in fonts:
        for path in filter(None, (font["regular"], font["bold"])):
            assert path.startswith("/usr/share/fonts/truetype/") and path.endswith(".ttf"), path
            assert packages[path.split("/")[5]] in manifest.apt_package_names(), path
    scripts = [f["script"] for f in fonts if f["script"] not in ("base", "symbols")]
    assert len(scripts) == len(set(scripts))
    assert {"arabic", "hebrew", "devanagari"} <= set(scripts)


def test_pdf_fonts_agree_with_the_fonts_the_model_is_told_about():
    """The model-facing FONTS table and the renderer's table name the same file for a shared script."""
    model_paths = {f["path"] for f in manifest.FONTS if f["reportlab"]}
    for script in ("base", "arabic", "devanagari"):
        regular = next(f["regular"] for f in manifest.PDF_FONTS if f["script"] == script)
        assert regular in model_paths, regular


def test_reportlab_can_shape_and_lay_out_right_to_left_text():
    """reportlab 4.4 added HarfBuzz shaping; the renderer joins Arabic and reorders RTL itself."""
    specs = dict(spec.split("==") for spec in manifest.pip_specs())
    major, minor = (int(part) for part in specs["reportlab"].split(".")[:2])
    assert (major, minor) >= (4, 4)
    assert {"uharfbuzz", "arabic-reshaper", "python-bidi"} <= set(specs)


# -- Environment, binaries, alternatives ---------------------------------------


def test_env_has_the_pip_and_tesseract_settings():
    assert manifest.ENV == {
        "PIP_ROOT_USER_ACTION": "ignore",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "OMP_THREAD_LIMIT": "1",
        "IMAGEIO_FFMPEG_EXE": "/usr/bin/ffmpeg",
        "NO_COLOR": "1",
    }


def test_env_file_is_one_safe_assignment_per_line():
    lines = [line for line in manifest.render_env_file().splitlines() if line and not line.startswith("#")]
    assert lines == [f"{k}={v}" for k, v in manifest.ENV.items()]
    for line in lines:
        assert re.fullmatch(r"[A-Z_][A-Z0-9_]*=[A-Za-z0-9_./:-]*", line)


def test_env_values_reject_shell_metacharacters():
    with pytest.raises(ValueError):
        manifest.render_env_file({"BAD": "a b"})
    with pytest.raises(ValueError):
        manifest.render_env_file({"bad-name": "1"})


def test_binaries_name_the_helpers_and_the_tools_models_shell_out_to():
    names = {b["name"] for b in manifest.BINARIES}
    assert {
        "office-convert",
        "html-to-pdf",
        "html-screenshot",
        "soffice",
        "chromium-headless-shell",
        "tesseract",
        "pdftotext",
        "pdftoppm",
        "node",
        "npm",
        "npx",
        "ffmpeg",
        "ffprobe",
    } <= names


def test_ffmpeg_comes_from_debian_not_a_bundled_wheel():
    """ffmpeg is Debian's package, a separate binary; the static builds in imageio-ffmpeg and PyAV stay out."""
    names = {manifest.dist_name(s).lower() for s in manifest.pip_specs(include_runner=True)}
    assert not names & {"imageio-ffmpeg", "av", "moviepy"}
    assert "ffmpeg" in manifest.apt_package_names()
    assert manifest.ENV["IMAGEIO_FFMPEG_EXE"] == "/usr/bin/ffmpeg"
    for name in ("imageio_ffmpeg", "av", "moviepy"):
        assert "ffmpeg command" in manifest.NOT_INSTALLED[name]["use"]


def test_every_helper_is_a_binary_with_a_source_file():
    helper_names = set(manifest.HELPERS)
    assert helper_names == {"office-convert", "html-to-pdf", "html-screenshot"}
    assert helper_names <= {b["name"] for b in manifest.BINARIES}
    for source in manifest.HELPERS.values():
        assert (_SANDBOX_DIR / source).is_file(), source


def test_not_installed_points_pymupdf_at_pdfplumber():
    for name in ("fitz", "pymupdf"):
        entry = manifest.NOT_INSTALLED[name]
        assert entry["package"] == "PyMuPDF"
        assert "pdfplumber" in entry["use"] and "pypdf" in entry["use"]
    imports = {p["import"] for p in manifest.PIP_PACKAGES}
    assert not set(manifest.NOT_INSTALLED) & imports


def test_not_installed_alternatives_name_something_the_image_has():
    """Each alternative points at a preinstalled package or a command, never at another missing one."""
    offered = {manifest.dist_name(p["spec"]).lower() for p in manifest.PIP_PACKAGES}
    offered |= {p["import"].lower() for p in manifest.PIP_PACKAGES}
    offered |= {b["name"] for b in manifest.BINARIES}
    for name, entry in manifest.NOT_INSTALLED.items():
        assert entry["package"], name
        words = set(re.findall(r"[A-Za-z0-9_.-]+", entry["use"].lower()))
        assert words & offered, name


def test_command_alternatives_are_missing_commands_with_a_present_replacement():
    commands = set(manifest.command_names())
    packages = {manifest.dist_name(p["spec"]).lower() for p in manifest.PIP_PACKAGES}
    for name, use in manifest.COMMAND_ALTERNATIVES.items():
        assert name not in commands, f"{name} is installed; it needs no alternative"
        assert any(c in use for c in commands) or any(p in use.lower() for p in packages), name
    for name in ("wkhtmltopdf", "pdftk", "google-chrome", "chromium"):
        assert name in manifest.COMMAND_ALTERNATIVES


def test_installed_imports_maps_import_names_to_packages():
    imports = manifest.installed_imports()
    assert imports["docx"] == "python-docx"
    assert imports["PIL"] == "pillow"
    assert imports["bs4"] == "beautifulsoup4"
    assert "kernel_gateway" not in imports
    assert len(imports) == len(manifest.PIP_PACKAGES)


def test_installed_packages_answers_by_pip_name_or_import_name():
    """``pip install docx`` and ``pip install python_docx`` both name the preinstalled python-docx."""
    for asked, expected in (
        ("python-docx", "python-docx"),
        ("python_docx", "python-docx"),
        ("docx", "python-docx"),
        ("Pillow", "pillow"),
        ("PyYAML", "PyYAML"),
        ("bs4", "beautifulsoup4"),
    ):
        assert manifest.installed_package(asked) == expected, asked
    assert manifest.installed_package("seaborn") is None


def test_command_names_are_the_commands_on_path():
    assert set(manifest.command_names()) == {b["name"] for b in manifest.BINARIES if b["on_path"]}


def test_format_guide_names_only_what_is_installed():
    packages = {manifest.dist_name(p["spec"]) for p in manifest.PIP_PACKAGES}
    commands = set(manifest.command_names())
    formats = {fmt for fmt, _ in manifest.FORMAT_GUIDE}
    assert {"pdf", "docx", "xlsx", "pptx"} <= formats
    # reportlab can't load the CJK collection or shape Arabic; Chromium can.
    assert "html-to-pdf for non-Latin text" in dict(manifest.FORMAT_GUIDE)["pdf"]
    for fmt, tools in manifest.FORMAT_GUIDE:
        named = set(re.findall(r"[A-Za-z0-9_-]+", tools))
        assert named & (packages | commands), fmt


def test_python_series_matches_the_runner_image():
    dockerfile = (_SANDBOX_DIR / "Dockerfile").read_text()
    assert f"FROM python:{manifest.PYTHON_SERIES}-slim" in dockerfile


def test_manifest_json_carries_what_the_smoke_test_checks():
    data = json.loads(manifest.render_manifest_json())
    assert [p["import"] for p in data["pip"]] == [p["import"] for p in manifest.PIP_PACKAGES]
    assert data["env"] == manifest.ENV
    assert {b["name"] for b in data["binaries"]} == {b["name"] for b in manifest.BINARIES}
    assert [f["path"] for f in data["fonts"]] == [f["path"] for f in manifest.FONTS]
    assert data["pdf_fonts"] == [dict(f) for f in manifest.PDF_FONTS]
    assert data["node"]["version"] == manifest.NODE["version"]


# -- Model-facing text -----------------------------------------------------------


def _words(text: str) -> int:
    return len(text.split())


def test_description_note_lists_import_names_commands_and_formats():
    text = manifest.description_note()
    for pkg in manifest.PIP_PACKAGES:
        assert pkg["import"] in text, pkg["import"]
    for name in ("office-convert", "html-to-pdf", "html-screenshot", "tesseract", "pdftotext", "ffmpeg", "node"):
        assert name in text, name
    for fmt, tools in manifest.FORMAT_GUIDE:
        assert f"{fmt}: {tools}" in text
    # The description stays short: fonts and usage lines go in the new-session summary.
    assert "/usr/share/fonts" not in text
    assert _words(text) <= 80


def test_environment_summary_covers_packages_commands_fonts_paths_and_limits():
    text = manifest.environment_summary(timeout=60, idle_minutes=20)
    for pkg in manifest.PIP_PACKAGES:
        assert pkg["import"] in text, pkg["import"]
    for binary in manifest.BINARIES:
        assert binary["name"] in text, binary["name"]
    assert "office-convert FILE --to pdf" in text
    for font in manifest.FONTS:
        assert font["path"].rsplit("/", 1)[-1] in text, font["path"]
    assert "/usr/share/fonts/" in text
    for path in ("inputs/", "scratch/", "/tmp"):
        assert path in text
    assert "60s" in text and "20 min" in text
    assert "jupyter" not in text.lower()


def test_environment_summary_stays_under_120_words():
    assert _words(manifest.environment_summary(timeout=60, idle_minutes=20)) <= 120
    assert _words(manifest.environment_summary(timeout=60, idle_minutes=20, max_timeout=1000)) <= 125


def test_environment_summary_names_the_longest_timeout_a_call_may_ask_for():
    text = manifest.environment_summary(timeout=60, idle_minutes=20, max_timeout=1000)
    assert "60s per call by default, `timeout` up to 1000s" in text
    # No longer cap to offer: the clause is left out.
    assert "`timeout`" not in manifest.environment_summary(timeout=60, idle_minutes=20, max_timeout=60)
    assert "`timeout`" not in manifest.environment_summary(timeout=60, idle_minutes=20)


def test_font_table_names_each_font_with_its_full_path_and_scripts():
    table = manifest.font_table()
    for font in manifest.FONTS:
        assert font["path"] in table
        assert font["scripts"].split(";")[0] in table


def test_font_table_for_reportlab_leaves_out_fonts_it_cannot_load():
    table = manifest.font_table(reportlab=True)
    assert "NotoSansCJK-Regular.ttc" not in table
    assert "DejaVuSans.ttf" in table
    assert all(f["path"] in table for f in manifest.FONTS if f["reportlab"])


# -- Importable without the app ------------------------------------------------


def test_manifest_imports_with_the_stdlib_only():
    """The export script and CI load the manifest without installing the backend."""
    code = (
        "import sys, docsgpt.sandbox.manifest as m; "
        "heavy = [n for n in sys.modules if n.startswith(('pydantic', 'docsgpt.core', 'daytona'))]; "
        "assert not heavy, heavy"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=_REPO, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
