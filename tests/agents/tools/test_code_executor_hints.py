"""Fix hints the code executor adds to a run_code result, and the output clean-up before tailing.

Each hint answers a mistake models made in production run_code calls: a missing
import, a pip install of a preinstalled package, apt-get, state lost between
calls, the time cap, a missing command, fetching the app's own URLs, deliverables
written outside the workspace, previews saved as downloads, missing fonts, silent
runs and retrying the same failure.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from docsgpt.agents.tools.code_executor_hints import (
    FailureMemory,
    RunFacts,
    clean_output,
    error_signature,
    fix_hints,
)
from docsgpt.sandbox import manifest
from docsgpt.sandbox.base import ExecResult


def _facts(
    code: str = "print(1)",
    result: Optional[ExecResult] = None,
    artifacts: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> RunFacts:
    return RunFacts(
        code=code,
        result=result if result is not None else ExecResult(status="ok", stdout="1\n"),
        artifacts=artifacts or [],
        **kwargs,
    )


def _error(name: str, value: str, **kwargs: Any) -> ExecResult:
    return ExecResult(status="error", error_name=name, error_value=value, **kwargs)


def _daytona_error(stdout: str) -> ExecResult:
    """Daytona reports a failed run as ExecutionError with the traceback on stdout."""
    return ExecResult(status="error", stdout=stdout, error_name="ExecutionError", error_value=stdout, exit_code=1)


def _one(hints: List[str], needle: str) -> str:
    matches = [h for h in hints if needle in h]
    assert len(matches) == 1, hints
    return matches[0]


# -- Output clean-up -------------------------------------------------------------


def test_clean_output_strips_ansi_colour_codes():
    assert clean_output("\x1b[31mred\x1b[0m and \x1b[1;32mgreen\x1b[0m\n") == "red and green\n"


def test_clean_output_strips_osc_sequences():
    assert clean_output("\x1b]8;;https://x\x07link\x1b]8;;\x07 done") == "link done"


def test_clean_output_drops_pip_noise_but_keeps_the_result_line():
    noisy = (
        "Requirement already satisfied: pandas in /usr/local/lib/python3.12/site-packages (2.2.3)\n"
        "Requirement already satisfied: numpy>=1.26 in /usr/local/lib/python3.12/site-packages (2.1.3)\n"
        "Collecting seaborn\n"
        "  Downloading seaborn-0.13.2-py3-none-any.whl.metadata (5.4 kB)\n"
        "WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour.\n"
        "\n"
        "[notice] A new release of pip is available: 24.0 -> 25.2\n"
        "[notice] To update, run: pip install --upgrade pip\n"
        "Successfully installed seaborn-0.13.2\n"
        "result: 42\n"
    )
    cleaned = clean_output(noisy)
    assert "Requirement already satisfied" not in cleaned
    assert "Running pip as the 'root' user" not in cleaned
    assert "[notice]" not in cleaned
    assert "Downloading" not in cleaned
    assert "Successfully installed seaborn-0.13.2" in cleaned
    assert "result: 42" in cleaned


def test_clean_output_keeps_the_last_frame_of_a_carriage_return_progress_line():
    assert clean_output("10%\r50%\r100%\ndone\n") == "100%\ndone\n"


def test_clean_output_leaves_plain_text_alone():
    text = "a,b\n1,2\n  indented line\n"
    assert clean_output(text) == text
    assert clean_output("") == ""
    assert clean_output(None) == ""


# -- 1. Missing module -------------------------------------------------------------


def test_missing_module_from_the_not_installed_list_names_the_alternative():
    hints = fix_hints(_facts("import fitz", _error("ModuleNotFoundError", "No module named 'fitz'")))
    hint = _one(hints, "fitz")
    assert "fitz (PyMuPDF) is not installed" in hint
    assert manifest.NOT_INSTALLED["fitz"]["use"] in hint


def test_missing_module_on_daytona_is_read_from_the_traceback():
    stdout = (
        "Traceback (most recent call last):\n"
        '  File "<string>", line 4, in <module>\n'
        "ModuleNotFoundError: No module named 'pdf2image'\n"
    )
    hints = fix_hints(_facts("from pdf2image import convert_from_path", _daytona_error(stdout), backend="daytona"))
    assert "pdftoppm" in _one(hints, "pdf2image")


def test_unknown_missing_module_says_prefer_preinstalled_or_pip_install_in_the_same_call():
    hints = fix_hints(_facts("import seaborn", _error("ModuleNotFoundError", "No module named 'seaborn'")))
    hint = _one(hints, "seaborn")
    assert "seaborn is not installed" in hint
    assert "preinstalled" in hint and "pip install it in the same call" in hint


def test_missing_submodule_of_an_installed_package_gets_no_not_installed_hint():
    hints = fix_hints(_facts("import docx.foo", _error("ModuleNotFoundError", "No module named 'docx.foo'")))
    assert not any("not installed" in h for h in hints)


def test_a_caught_and_printed_import_error_still_gets_the_hint():
    result = ExecResult(status="ok", stdout="failed: No module named 'camelot'\n")
    hints = fix_hints(_facts("try:\n    import camelot\nexcept Exception as e:\n    print('failed:', e)", result))
    assert "extract_tables" in _one(hints, "camelot")


def test_missing_module_on_a_bare_daytona_image_says_pip_install():
    hints = fix_hints(
        _facts("import pandas", _error("ModuleNotFoundError", "No module named 'pandas'"), full_image=False)
    )
    hint = _one(hints, "pandas")
    assert "only the Python stdlib" in hint and "pip install" in hint


# -- 2. pip install of a preinstalled package ----------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess\nsubprocess.run(['pip', 'install', 'pandas', 'openpyxl'])",
        (
            "import subprocess, sys\n"
            "subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'pandas', 'openpyxl'])"
        ),
        "!pip install -q pandas openpyxl",
        "%pip install --upgrade pandas==2.2.3 openpyxl",
        "import os\nos.system('pip install pandas openpyxl >/dev/null')",
    ],
)
def test_pip_installing_preinstalled_packages_says_drop_the_pip_step(code):
    hint = _one(fix_hints(_facts(code)), "already installed")
    assert "pandas" in hint and "openpyxl" in hint
    assert "drop the pip step" in hint


def test_pip_install_by_import_name_maps_to_the_package():
    hint = _one(fix_hints(_facts("!pip install docx")), "already installed")
    assert "python-docx" in hint


def test_pip_installing_a_new_package_gets_no_hint():
    assert not any("already installed" in h for h in fix_hints(_facts("!pip install seaborn")))


def test_pip_install_hint_is_skipped_on_a_bare_image():
    assert not any("already installed" in h for h in fix_hints(_facts("!pip install pandas", full_image=False)))


def test_pip_install_from_a_requirements_file_is_not_parsed_as_packages():
    assert not any("already installed" in h for h in fix_hints(_facts("!pip install -r requirements.txt")))


# -- 3. apt-get / sudo -----------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import subprocess\nsubprocess.run('apt-get update && apt-get install -y wkhtmltopdf', shell=True)",
        "!apt install -y pandoc",
        "import os\nos.system('sudo apt-get install -y ghostscript')",
    ],
)
def test_apt_get_says_system_packages_cannot_be_installed(code):
    hint = _one(fix_hints(_facts(code)), "System packages")
    assert "can't be installed here" in hint
    assert "office-convert" in hint and "tesseract" in hint


def test_apt_hint_on_daytona_explains_why_not_to():
    hint = _one(fix_hints(_facts("!apt-get install -y pandoc", backend="daytona")), "system packages")
    assert "60s" in hint and "office-convert" in hint


def test_the_word_apt_in_prose_is_not_apt_get():
    assert not any("ystem packages" in h for h in fix_hints(_facts("print('an apt description')")))


# -- 4. State lost between calls --------------------------------------------------------


def test_name_error_in_a_new_session_says_state_is_gone():
    hints = fix_hints(_facts("print(df.shape)", _error("NameError", "name 'df' is not defined"), session_new=True))
    hint = _one(hints, "session: new")
    assert "inputs=['A2', ...]" in hint


def test_file_not_found_in_a_new_session_says_state_is_gone():
    result = _error("FileNotFoundError", "[Errno 2] No such file or directory: 'cleaned.csv'")
    hints = fix_hints(_facts("pd.read_csv('cleaned.csv')", result, session_new=True))
    _one(hints, "session: new")


def test_name_error_in_a_reused_jupyter_session_is_just_a_bug():
    hints = fix_hints(_facts("print(dff)", _error("NameError", "name 'dff' is not defined"), session_new=False))
    assert hints == []


def test_name_error_on_daytona_says_each_call_is_a_fresh_interpreter():
    stdout = "Traceback (most recent call last):\nNameError: name 'df' is not defined\n"
    hints = fix_hints(_facts("print(df)", _daytona_error(stdout), backend="daytona", session_new=False))
    assert "re-import" in _one(hints, "fresh interpreter")


def test_file_not_found_under_tmp_says_tmp_is_not_kept():
    result = _error("FileNotFoundError", "[Errno 2] No such file or directory: '/tmp/data.parquet'")
    hints = fix_hints(_facts("pd.read_parquet('/tmp/data.parquet')", result, session_new=False))
    hint = _one(hints, "/tmp is not kept")
    assert "scratch/" in hint


# -- 5. Timeout -----------------------------------------------------------------------


def test_timeout_says_unsaved_work_is_lost_and_to_write_partials():
    result = _error("TimeoutError", "execution exceeded 60.0s")
    hint = _one(fix_hints(_facts("train()", result, timed_out=True)), "interrupted")
    assert "scratch/" in hint and "chunks" in hint


def test_timeout_below_the_max_suggests_a_larger_timeout():
    result = _error("TimeoutError", "execution exceeded 60.0s")
    hints = fix_hints(_facts("render()", result, timed_out=True, timeout=60, max_timeout=1000))
    hint = _one(hints, "`timeout`")
    assert "1000" in hint


def test_timeout_at_the_max_does_not_suggest_a_larger_timeout():
    result = _error("TimeoutError", "execution exceeded 1000.0s")
    hints = fix_hints(_facts("render()", result, timed_out=True, timeout=1000, max_timeout=1000))
    assert not any("`timeout`" in h for h in hints), hints
    _one(hints, "interrupted")


def test_timeout_without_a_known_max_does_not_suggest_a_larger_timeout():
    result = _error("TimeoutError", "execution exceeded 60.0s")
    hints = fix_hints(_facts("render()", result, timed_out=True, timeout=60))
    assert not any("`timeout`" in h for h in hints), hints


# -- 5b. Out of memory ------------------------------------------------------------------


_OOM_RESULTS = [
    # The backend saw the process killed for memory (Jupyter kernel death with an OOM kill,
    # Daytona exit 137).
    ExecResult(status="error", error_name="KernelDiedError", error_value="died", exit_code=-1, out_of_memory=True),
    # A subprocess the code started was killed by SIGKILL.
    _error("CalledProcessError", "Command '['ffmpeg', '-i', 'x.mp4']' died with <Signals.SIGKILL: 9>."),
    _error("CalledProcessError", "Command 'ffmpeg -i x.mp4' returned non-zero exit status 137."),
    ExecResult(status="ok", stdout="child rc -9\n"),
    ExecResult(status="ok", stdout="", stderr="/bin/sh: line 1:    42 Killed                  python big.py\n"),
    # Python could not allocate.
    _error("MemoryError", ""),
    _error("MemoryError", "Unable to allocate 7.45 GiB for an array with shape (1000000000,) and data type float64"),
    _error("ArrayMemoryError", "Unable to allocate 7.45 GiB for an array"),
]


@pytest.mark.parametrize("result", _OOM_RESULTS)
def test_out_of_memory_says_to_process_in_chunks(result):
    hint = _one(fix_hints(_facts("process()", result)), "memory")
    assert "chunks" in hint


@pytest.mark.parametrize(
    "result",
    [
        _error("ValueError", "invalid literal for int() with base 10: '-9'"),
        ExecResult(status="ok", stdout="exit status 1370 rows\n"),
        ExecResult(status="ok", stdout="Killed it!\n"),
        _error("CalledProcessError", "Command 'false' returned non-zero exit status 1."),
    ],
)
def test_ordinary_failures_are_not_called_out_of_memory(result):
    assert not any("memory" in h for h in fix_hints(_facts("x()", result)))


def test_out_of_memory_on_a_timeout_is_not_reported():
    """A timeout kills the run too; it must not be read as out of memory."""
    result = _error("TimeoutError", "execution exceeded 60.0s")
    hints = fix_hints(_facts("x()", result, timed_out=True, timeout=60, max_timeout=1000))
    assert not any("memory" in h for h in hints)


# -- 6. Missing command ------------------------------------------------------------------


def test_missing_binary_from_subprocess_names_the_replacement():
    result = _error("FileNotFoundError", "[Errno 2] No such file or directory: 'wkhtmltopdf'")
    hints = fix_hints(_facts("subprocess.run(['wkhtmltopdf', 'a.html', 'a.pdf'])", result, session_new=True))
    hint = _one(hints, "wkhtmltopdf")
    assert "`wkhtmltopdf` is not available" in hint
    assert "Use html-to-pdf" in hint
    assert "Available commands:" in hint
    # A missing command is not lost session state.
    assert not any("session: new" in h for h in hints)


@pytest.mark.parametrize(
    "stderr",
    [
        "/bin/sh: 1: pdftk: not found\n",
        "bash: pdftk: command not found\n",
        "sh: line 1: pdftk: command not found\n",
    ],
)
def test_command_not_found_in_shell_output(stderr):
    result = ExecResult(status="ok", stdout="", stderr=stderr)
    hint = _one(fix_hints(_facts("os.system('pdftk a.pdf b.pdf cat output c.pdf')", result)), "pdftk")
    assert "pypdf" in hint


def test_shutil_which_on_a_known_missing_command():
    result = ExecResult(status="ok", stdout="None\n")
    hint = _one(fix_hints(_facts("import shutil\nprint(shutil.which('google-chrome'))", result)), "google-chrome")
    assert "html-to-pdf" in hint


def test_missing_command_without_a_known_replacement_lists_what_exists():
    result = _error("FileNotFoundError", "[Errno 2] No such file or directory: 'blender'")
    hint = _one(fix_hints(_facts("subprocess.run(['blender'])", result)), "blender")
    assert "Available commands:" in hint and "Use " not in hint


# -- 7. The app's own URLs ----------------------------------------------------------------


def test_fetching_an_artifact_url_says_pass_it_as_an_input():
    url = "https://app.example.com/api/artifacts/abc/download"
    code = f"import requests\nr = requests.get('{url}')\nr.raise_for_status()"
    result = _error("HTTPError", f"403 Client Error: Forbidden for url: {url}")
    hint = _one(fix_hints(_facts(code, result)), "Artifact/app URLs")
    assert "inputs=['A3']" in hint


def test_fetching_the_deployment_host_matches_by_hostname():
    code = "requests.get('https://docs.example.org/c/123')"
    result = ExecResult(status="ok", stdout="status 401\n")
    hints = fix_hints(_facts(code, result, app_hosts=("docs.example.org",)))
    _one(hints, "Artifact/app URLs")


def test_a_connection_error_to_the_local_api_matches_by_port():
    code = "requests.get('http://localhost:7091/api/artifacts/x/download')"
    result = _error("ConnectionError", "Max retries exceeded with url: /api/artifacts/x/download")
    _one(fix_hints(_facts(code, result, app_hosts=("localhost:7091",))), "Artifact/app URLs")


def test_a_failing_public_url_is_not_an_app_url():
    code = "requests.get('https://example.net/data.csv')"
    result = _error("HTTPError", "403 Client Error: Forbidden for url: https://example.net/data.csv")
    assert not any("Artifact/app" in h for h in fix_hints(_facts(code, result, app_hosts=("app.example.com",))))


def test_a_successful_fetch_of_an_app_url_gets_no_hint():
    code = "requests.get('https://app.example.com/api/health')"
    result = ExecResult(status="ok", stdout="200\n")
    assert fix_hints(_facts(code, result, app_hosts=("app.example.com",))) == []


# -- 8. Deliverables outside the workspace ---------------------------------------------------


@pytest.mark.parametrize(
    "code, path",
    [
        ("plt.savefig('/tmp/chart.png')", "/tmp/chart.png"),
        ("doc.save('/mnt/data/report.docx')", "/mnt/data/report.docx"),
        ("df.to_csv(\"/home/user/out.csv\")", "/home/user/out.csv"),
        ("with open('/tmp/r.pdf', 'wb') as f:\n    f.write(data)", "/tmp/r.pdf"),
        ("out = '/tmp/{name}.xlsx'\nwb.save(out)", "/tmp/{name}.xlsx"),
    ],
)
def test_deliverable_written_outside_the_workspace_was_not_saved(code, path):
    hint = _one(fix_hints(_facts(code)), "outside the workspace")
    assert path in hint and "NOT saved" in hint
    assert f"`{path.rsplit('/', 1)[-1]}`" in hint


@pytest.mark.parametrize(
    "code",
    [
        "pd.read_csv('/tmp/input.csv')",
        "with open('/tmp/in.pdf', 'rb') as f:\n    data = f.read()",
        "load_workbook('/mnt/data/book.xlsx')",
        "Image.open('/tmp/photo.jpg')",
        "plt.savefig('/tmp/docsgpt-sandbox/conv-1/chart.png')",
        "font = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'",
        "plt.savefig('chart.png')",
    ],
)
def test_reads_workspace_paths_and_non_deliverables_are_not_flagged(code):
    assert not any("outside the workspace" in h for h in fix_hints(_facts(code)))


def test_outside_path_is_not_flagged_when_a_matching_artifact_was_captured():
    artifacts = [{"filename": "chart.png", "mime_type": "image/png"}]
    hints = fix_hints(_facts("plt.savefig('/tmp/chart.png')\nplt.savefig('chart.png')", artifacts=artifacts))
    assert not any("outside the workspace" in h for h in hints)


def test_outside_path_is_not_flagged_on_a_failed_run():
    result = _error("ValueError", "bad")
    assert not any("outside the workspace" in h for h in fix_hints(_facts("plt.savefig('/tmp/c.png')", result)))


# -- 9. Previews saved as downloads -------------------------------------------------------------


def _image(name: str) -> Dict[str, Any]:
    return {"filename": name, "mime_type": "image/png"}


def test_more_than_three_images_says_put_previews_in_scratch():
    artifacts = [_image(f"page{i}.png") for i in range(4)]
    hint = _one(fix_hints(_facts("render()", artifacts=artifacts)), "Saved for the user")
    assert "page0.png" in hint and "page3.png" in hint and "scratch/" in hint


@pytest.mark.parametrize("name", ["preview.png", "test_render.pdf", "tmp-chart.png", "debug.txt", "check_page1.png"])
def test_preview_like_names_say_put_previews_in_scratch(name):
    artifacts = [{"filename": name, "mime_type": "application/octet-stream"}, {"filename": "report.pdf"}]
    hint = _one(fix_hints(_facts("render()", artifacts=artifacts)), "Saved for the user")
    assert name in hint and "report.pdf" not in hint


def test_three_real_charts_are_fine():
    artifacts = [_image("sales.png"), _image("costs.png"), _image("margin.png")]
    assert fix_hints(_facts("plot()", artifacts=artifacts)) == []


# -- 10. Fonts --------------------------------------------------------------------------------


def test_reportlab_ttf_error_lists_the_installed_fonts():
    result = _error("TTFError", "Can't open file \"/usr/share/fonts/truetype/msttcorefonts/Arial.ttf\"")
    code = "TTFont('Arial', '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf')"
    hint = _one(fix_hints(_facts(code, result)), "Font")
    assert "Font /usr/share/fonts/truetype/msttcorefonts/Arial.ttf not found" in hint
    assert manifest.font_table() in hint


def test_pil_cannot_open_resource_takes_the_path_from_the_code():
    result = _error("OSError", "cannot open resource")
    hint = _one(fix_hints(_facts("ImageFont.truetype('arial.ttf', 24)", result)), "not found")
    assert "Font arial.ttf not found" in hint


def test_missing_glyph_warnings_list_the_fonts_by_script():
    result = ExecResult(
        status="ok",
        stderr="UserWarning: Glyph 20013 (\\N{CJK UNIFIED IDEOGRAPH-4E2D}) missing from font(s) DejaVu Sans.\n",
    )
    hint = _one(fix_hints(_facts("plt.title('中文')", result, artifacts=[_image("c.png")])), "glyphs")
    assert "NotoSansCJK-Regular.ttc" in hint


def test_reportlab_with_non_latin_text_and_no_registered_font():
    code = "from reportlab.platypus import Paragraph\nstory.append(Paragraph('Привет мир'))"
    hint = _one(fix_hints(_facts(code, artifacts=[{"filename": "r.pdf"}])), "Helvetica")
    assert "html-to-pdf" in hint
    assert "registerFont" in hint and "DejaVuSans.ttf" in hint
    # reportlab cannot load the CJK collection, so it is not offered for registerFont.
    assert "NotoSansCJK" not in hint


def test_a_cff_font_reportlab_cannot_load_is_not_called_missing():
    """reportlab rejects the Noto CJK collection (PostScript outlines); the file is there."""
    path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    result = _error("TTFError", f'TTC file "{path}": postscript outlines are not supported')
    hint = _one(fix_hints(_facts(f"TTFont('cjk', '{path}')", result)), "PostScript")
    assert "not found" not in hint
    assert "html-to-pdf" in hint and "UnicodeCIDFont('STSong-Light')" in hint


def test_a_compiled_package_installed_at_runtime_that_cannot_load():
    result = _error(
        "ImportError",
        "/tmp/home/.local/lib/python3.12/site-packages/bidi/bidi.cpython-312-aarch64-linux-gnu.so: "
        "failed to map segment from shared object",
    )
    hint = _one(fix_hints(_facts("import bidi", result)), "compiled")
    assert "bidi" in hint and "preinstalled" in hint


def test_a_top_level_compiled_module_that_cannot_load_is_named():
    result = _error(
        "ImportError",
        "/tmp/home/.local/lib/python3.12/site-packages/ujson.cpython-312-x86_64-linux-gnu.so: "
        "failed to map segment from shared object",
    )
    hint = _one(fix_hints(_facts("import ujson", result)), "compiled")
    assert hint.startswith("ujson ")


def test_the_compiled_package_hint_needs_the_noexec_load_error():
    """With the exec-enabled home mount pip-installed extensions load; the hint fires only on the real error."""
    loaded = ExecResult(status="ok", stdout="msgpack 1.1.0 from /sandbox-home/home/.local/lib/python3.12/\n")
    assert not any("compiled" in h for h in fix_hints(_facts("import msgpack", loaded)))
    other = _error("ImportError", "/usr/local/lib/python3.12/site-packages/x/x.so: undefined symbol: foo")
    assert not any("compiled" in h for h in fix_hints(_facts("import x", other)))


def test_reportlab_with_a_registered_font_is_fine():
    code = (
        "from reportlab.pdfbase.ttfonts import TTFont\n"
        "pdfmetrics.registerFont(TTFont('DejaVu', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))\n"
        "Paragraph('Привет')"
    )
    assert fix_hints(_facts(code, artifacts=[{"filename": "r.pdf"}])) == []


def test_reportlab_with_latin_accents_only_is_fine():
    code = "from reportlab.platypus import Paragraph\nParagraph('Café crème – “quotes”')"
    assert fix_hints(_facts(code, artifacts=[{"filename": "r.pdf"}])) == []


# -- 11. Silent run ----------------------------------------------------------------------------


def test_silent_successful_run_says_print_the_results():
    hint = _one(fix_hints(_facts("x = 1 + 1", ExecResult(status="ok", stdout=""))), "No output")
    assert "print()" in hint


def test_silent_run_with_pip_noise_only_is_still_silent():
    noise = "Requirement already satisfied: pandas in /usr/lib (2.2.3)\n"
    _one(fix_hints(_facts("df.describe()", ExecResult(status="ok", stdout=noise))), "No output")


@pytest.mark.parametrize(
    "facts_kwargs",
    [
        {"artifacts": [{"filename": "a.csv"}]},
        {"charts_shown": 1},
        {"capture": False},
        {"result": ExecResult(status="ok", stdout="", stderr="warning\n")},
    ],
)
def test_runs_that_produced_something_are_not_silent(facts_kwargs):
    kwargs = {"result": ExecResult(status="ok", stdout="")}
    kwargs.update(facts_kwargs)
    assert not any("No output" in h for h in fix_hints(_facts("x = 1", **kwargs)))


# -- Bounds ---------------------------------------------------------------------------------------


def test_hints_are_short_and_capped():
    code = (
        "!apt-get install -y wkhtmltopdf\n!pip install pandas\nimport fitz\nimport seaborn\n"
        "plt.savefig('/tmp/a.png')"
    )
    result = ExecResult(
        status="ok",
        stdout="No module named 'fitz'\nNo module named 'seaborn'\nNo module named 'cv2'\n",
        stderr="/bin/sh: 1: wkhtmltopdf: not found\n",
    )
    hints = fix_hints(_facts(code, result))
    assert 1 <= len(hints) <= 4
    for hint in hints:
        assert hint.count("\n") <= 1
        assert len(hint) <= 700, hint


def test_hints_are_deduplicated():
    result = ExecResult(status="ok", stdout="No module named 'fitz'\nNo module named 'fitz'\n")
    assert len(fix_hints(_facts("import fitz", result))) == 1


# -- 12. Repeated failure ------------------------------------------------------------------------


def test_error_signature_ignores_numbers_and_addresses():
    a = _error("KeyError", "'col_17' at 0x7f3a2c")
    b = _error("KeyError", "'col_18' at 0x7f3b9d")
    assert error_signature(a) == error_signature(b)
    assert error_signature(a) != error_signature(_error("ValueError", "'col_17' at 0x7f3a2c"))


def test_error_signature_reads_daytona_tracebacks_and_ignores_successes():
    stdout = "Traceback (most recent call last):\nZeroDivisionError: division by zero\n"
    assert error_signature(_daytona_error(stdout)) == error_signature(_error("ZeroDivisionError", "division by zero"))
    assert error_signature(ExecResult(status="ok")) is None


def test_failure_memory_flags_the_same_failure_twice_in_a_row():
    memory = FailureMemory(max_sessions=8)
    assert memory.repeated("s1", "KeyError:x") is False
    assert memory.repeated("s1", "KeyError:x") is True
    assert memory.repeated("s1", "KeyError:x") is True
    assert memory.repeated("s2", "KeyError:x") is False


def test_failure_memory_resets_on_success_or_a_different_failure():
    memory = FailureMemory(max_sessions=8)
    memory.repeated("s1", "KeyError:x")
    assert memory.repeated("s1", None) is False
    assert memory.repeated("s1", "KeyError:x") is False
    assert memory.repeated("s1", "ValueError:y") is False
    assert memory.repeated("s1", "KeyError:x") is False


def test_failure_memory_is_bounded():
    memory = FailureMemory(max_sessions=2)
    memory.repeated("a", "E")
    memory.repeated("b", "E")
    memory.repeated("c", "E")
    assert memory.repeated("a", "E") is False  # evicted
    assert memory.repeated("c", "E") is True


# -- Edge cases -----------------------------------------------------------------------------------------


def test_jupyter_traceback_lines_are_scanned_without_colour_codes():
    result = _error(
        "CalledProcessError",
        "Command '['soffice']' returned non-zero exit status 1.",
        traceback=["\x1b[31m/bin/sh: 1: pdftk: not found\x1b[0m"],
    )
    hint = _one(fix_hints(_facts("os.system('pdftk a.pdf cat output b.pdf')", result)), "pdftk")
    assert "pypdf" in hint


def test_an_unnamed_error_keeps_its_message_in_the_signature():
    assert error_signature(ExecResult(status="error", error_value="boom 42")) == "error:boom #"


def test_malformed_and_hostless_urls_are_not_app_urls():
    result = _error("ConnectionError", "Max retries exceeded")
    for url in ("http://[::1", "http:///no-host"):
        assert not any("Artifact/app" in h for h in fix_hints(_facts(f"requests.get('{url}')", result)))
