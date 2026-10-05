"""Fix hints for ``run_code`` results, and the clean-up applied to output before it is tailed.

Models repeat the same sandbox mistakes: importing a library the image lacks,
pip-installing one it has, running apt-get, expecting variables or ``/tmp``
files to outlive a call, writing deliverables outside the workspace, saving
previews as downloads, hardcoding font paths, fetching the app's own URLs from
inside the sandbox, running out of time or memory, and retrying a failure
unchanged. ``fix_hints`` reads one
run (its code, output, error and saved files) and returns a line or two for
each mistake it recognizes. Package, command and font names come from
``docsgpt/sandbox/manifest.py``, so the hints never name something the image
does not hold.

The checks are deliberately light: substring and regex matches on the output and
the submitted code. A missed hint costs nothing; a wrong one misleads the model,
so each check errs towards staying quiet.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from docsgpt.sandbox import manifest
from docsgpt.sandbox.base import ExecResult
from docsgpt.sandbox.daytona import _WORKSPACE_ROOT as _DAYTONA_WORKSPACE
from docsgpt.sandbox.jupyter_gateway import _WORKSPACE_ROOT as _JUPYTER_WORKSPACE

# At most this many hints per result; the first ones are the most specific.
MAX_HINTS = 4

# -- Output clean-up ---------------------------------------------------------------

# CSI sequences (colours, cursor moves), OSC sequences (hyperlinks, titles) and
# the remaining two-character escapes.
_ANSI_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")

# Lines pip prints that carry nothing the model needs. "Successfully installed"
# and every error line are kept.
_PIP_NOISE_RE = re.compile(
    r"^\s*(?:"
    r"Requirement already satisfied:"
    r"|WARNING: Running pip as the 'root' user"
    r"|\[notice\]"
    r"|(?:Collecting|Downloading|Using cached|Obtaining) \S"
    r"|[─-╿\s]*[─-╿][─-╿\s]*[\d.]+/?[\d.]*\s*\S*B\b"
    r")"
)


def clean_output(text: Optional[str]) -> str:
    """Strip colour codes, carriage-return progress frames and pip noise from captured output.

    Args:
        text: stdout or stderr of a run, or None.

    Returns:
        The text with ANSI escape sequences removed, each line reduced to its last
        carriage-return frame, and pip's routine lines dropped. Other lines are
        kept as they are.
    """
    if not text:
        return ""
    text = _ANSI_RE.sub("", text)
    lines = []
    for line in text.split("\n"):
        if "\r" in line:
            frames = [frame for frame in line.split("\r") if frame]
            line = frames[-1] if frames else ""
        if _PIP_NOISE_RE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


# -- Reading a run --------------------------------------------------------------------

# Error names a backend reports for "the process failed" without saying how;
# the real exception is then on the last traceback line of the output.
GENERIC_ERROR_NAMES = frozenset({"ExecutionError"})

# The last line of a Python traceback: ``[module.]SomeError: message``.
_EXCEPTION_LINE_RE = re.compile(
    r"^(?:[A-Za-z_]\w*\.)*([A-Za-z_]\w*(?:Error|Exception|Exit|Interrupt)|StopIteration)(?::[ \t]*(.*))?$",
    re.MULTILINE,
)


def _text_of(result: ExecResult) -> str:
    """Return everything the run printed or raised, cleaned, as one string to scan."""
    parts = [clean_output(result.stdout), clean_output(result.stderr)]
    if result.error_value and result.error_value != result.stdout:
        parts.append(clean_output(f"{result.error_name or 'Error'}: {result.error_value}"))
    if result.traceback:
        parts.append(clean_output("\n".join(str(line) for line in result.traceback)))
    return "\n".join(part for part in parts if part)


def exception_of(result: ExecResult) -> Tuple[Optional[str], str]:
    """Return the exception a failed run raised as ``(name, message)``; ``(None, "")`` on success."""
    if result.ok:
        return None, ""
    name = result.error_name
    if name and name not in GENERIC_ERROR_NAMES:
        return name, clean_output(result.error_value or "")
    matches = list(_EXCEPTION_LINE_RE.finditer(_text_of(result)))
    if matches:
        last = matches[-1]
        return last.group(1), (last.group(2) or "").strip()
    return name, clean_output(result.error_value or "")


def error_signature(result: ExecResult) -> Optional[str]:
    """Identify a failure so a repeat of it can be recognized.

    Args:
        result: The run's result.

    Returns:
        ``"ExceptionName:normalized message"`` (numbers and addresses masked, so the
        same mistake on another row or object still matches), or None for a run
        that succeeded.
    """
    name, message = exception_of(result)
    if name is None and result.ok:
        return None
    message = re.sub(r"0x[0-9a-fA-F]+", "0x", message.lower())
    message = re.sub(r"\d+", "#", message)
    message = " ".join(message.split())[:160]
    return f"{name or 'error'}:{message}"


@dataclass(frozen=True)
class RunFacts:
    """What one ``run_code`` call did, as the hints need it.

    Attributes:
        code: The submitted source.
        result: The backend's result.
        artifacts: References of the files saved for the user (``filename``, ``mime_type``).
        session_new: The call started a fresh session.
        backend: ``jupyter`` or ``daytona``.
        full_image: The sandbox runs the manifest's image; False for a bare Daytona sandbox.
        timed_out: The run hit the wall-clock cap.
        timeout: The cap in seconds.
        max_timeout: The longest cap a call may ask for; 0 when unknown.
        app_hosts: This deployment's own hosts, ``host`` or ``host:port``.
        capture: Saving files for the user was on.
        charts_shown: Charts the run displayed to the model.
    """

    code: str
    result: ExecResult
    artifacts: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    session_new: bool = False
    backend: str = "jupyter"
    full_image: bool = True
    timed_out: bool = False
    timeout: int = 60
    max_timeout: int = 0
    app_hosts: Tuple[str, ...] = ()
    capture: bool = True
    charts_shown: int = 0


def _commands() -> str:
    return ", ".join(manifest.command_names())


def _unique(items: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(items))


# -- 1. Missing modules -----------------------------------------------------------------

_NO_MODULE_RE = re.compile(r"No module named '([\w.]+)'")


def _missing_module_hints(facts: RunFacts, text: str) -> List[str]:
    installed = manifest.installed_imports() if facts.full_image else {}
    hints = []
    for module in _unique(m.split(".")[0] for m in _NO_MODULE_RE.findall(text)):
        if module in installed:
            continue  # a missing submodule of a preinstalled package: a code bug, not an install
        if not facts.full_image:
            hints.append(
                f"{module} is not installed: this sandbox has only the Python stdlib. "
                "pip install it in the same call before importing it."
            )
            continue
        missing = manifest.NOT_INSTALLED.get(module) or manifest.NOT_INSTALLED.get(module.lower())
        if missing:
            same = missing["package"].lower().replace("-", "_") == module.lower()
            label = module if same else f"{module} ({missing['package']})"
            hints.append(f"{label} is not installed. Use {missing['use']}.")
        else:
            hints.append(
                f"{module} is not installed. Prefer a preinstalled library; if {module} is really needed, "
                "pip install it in the same call."
            )
    return hints[:2]


# The package (``bidi/...so``) or top-level module (``ujson.cpython-...so``) whose extension failed to load.
_CANNOT_MAP_RE = re.compile(r"/site-packages/(\w+)[^\s'\"]*\.so[^\n]*failed to map segment from shared object")


def _compiled_package_hint(text: str) -> Optional[str]:
    """A package pip-installed at runtime whose compiled extension the sandbox won't load.

    The runner keeps the kernels' home, where ``pip install --user`` puts
    packages, on an exec-enabled mount (deployment/sandbox/kernel-env.sh), so
    compiled packages load. A runner started without that mount falls back to a
    home under the noexec /tmp, where loading the extension fails with this
    error; only then does the hint fire.
    """
    match = _CANNOT_MAP_RE.search(text)
    if not match:
        return None
    return (
        f"{match.group(1)} was installed at runtime but its compiled code can't load in this sandbox (its home "
        "is on a noexec mount). Use a preinstalled library or a pure-Python package instead."
    )


# -- 2. pip install of a preinstalled package ---------------------------------------------

_PIP_INSTALL_RE = re.compile(r"""\bpip3?\b['"]?\s*,?\s*['"]?install\b(?P<rest>[^\n]*)""")
# pip options whose next token is a value, not a package.
_PIP_VALUE_OPTIONS = frozenset(
    {
        "-r", "--requirement", "-c", "--constraint", "-e", "--editable", "-i", "--index-url",
        "--extra-index-url", "-f", "--find-links", "-t", "--target", "--trusted-host", "--prefix",
        "--root", "--platform", "--python-version", "--implementation", "--abi", "--src", "--cache-dir",
        "--progress-bar", "--root-user-action",
    }
)
_PACKAGE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _pip_targets(code: str) -> List[str]:
    """Return the package names the code pip-installs, version specifiers removed."""
    targets: List[str] = []
    for match in _PIP_INSTALL_RE.finditer(code):
        rest = match.group("rest")
        lead = re.match(r"""[\s'",]*""", rest).group(0)
        if any(ch in lead for ch in "'\","):
            rest = re.split(r"[\])]", rest, maxsplit=1)[0]  # list form: ["pip", "install", "x"]
        else:
            rest = re.split(r"""['"]|&&|\|\||[;|>#)]""", rest, maxsplit=1)[0]  # one command string
        skip_next = False
        for token in re.findall(r"""[^\s'",\[\]()]+""", rest):
            if skip_next:
                skip_next = False
                continue
            if token.startswith("-"):
                skip_next = token in _PIP_VALUE_OPTIONS
                continue
            name = re.split(r"[<>=!~\[;@]", token, maxsplit=1)[0]
            if _PACKAGE_TOKEN_RE.fullmatch(name):
                targets.append(name)
    return targets


def _pip_hint(facts: RunFacts) -> Optional[str]:
    if not facts.full_image:
        return None
    labels = []
    for asked in _pip_targets(facts.code):
        package = manifest.installed_package(asked)
        if package is None:
            continue
        normalized = re.sub(r"[-_.]+", "-", asked).lower()
        same = normalized == re.sub(r"[-_.]+", "-", package).lower()
        labels.append(package if same else f"{package} (import {asked})")
    labels = _unique(labels)
    if not labels:
        return None
    verb = "is" if len(labels) == 1 else "are"
    return f"{', '.join(labels)} {verb} already installed; drop the pip step."


# -- 3. apt-get, apt, sudo ----------------------------------------------------------------

_APT_RE = re.compile(r"(?<![\w-])(?:apt-get\s|apt\s+(?:-\S+\s+)*(?:install|update|upgrade|remove)\b|sudo\s+\S)")


def _apt_hint(facts: RunFacts) -> Optional[str]:
    if not facts.full_image or not _APT_RE.search(facts.code):
        return None
    if facts.backend == "daytona":
        return (
            f"Don't install system packages here: it rarely fits the {facts.timeout}s cap and is lost when "
            f"the session resets. Available commands: {_commands()}."
        )
    return f"System packages can't be installed here (no root). Available commands: {_commands()}."


# -- 4 and 6. Missing files and commands ----------------------------------------------------

_NO_SUCH_FILE_RE = re.compile(r"No such file or directory: '([^'\n]+)'")
_SHELL_NOT_FOUND_RE = re.compile(
    r"^(?:/usr)?(?:/bin/)?(?:ba|da|z)?sh(?:: line \d+)?: (?:\d+: )?([\w.+-]+): (?:command )?not found",
    re.MULTILINE,
)
_WHICH_RE = re.compile(r"""shutil\.which\(\s*['"]([\w.+-]+)['"]""")
_RUNS_COMMANDS_RE = re.compile(r"subprocess|Popen|os\.system|os\.popen|check_output|check_call|os\.exec|^\s*!", re.M)
_COMMAND_DIRS = ("/usr/bin/", "/usr/local/bin/", "/bin/", "/opt/", "/usr/sbin/")
_FONT_FILE_RE = re.compile(r"\.(?:ttf|otf|ttc)$", re.IGNORECASE)
_NAME_ERROR_RE = re.compile(r"name '(\w+)' is not defined")


def _is_command_path(path: str, code: str) -> bool:
    """True when a missing path is a command the code tried to run rather than a data file."""
    base = path.rsplit("/", 1)[-1]
    if "/" in path and not path.startswith(_COMMAND_DIRS):
        return False
    if "." in base and base not in manifest.COMMAND_ALTERNATIVES:
        return False
    return bool(_RUNS_COMMANDS_RE.search(code)) and bool(re.search(rf"""['"\s/]{re.escape(base)}\b""", code))


def _missing_commands(facts: RunFacts, text: str) -> List[str]:
    names = [p.rsplit("/", 1)[-1] for p in _NO_SUCH_FILE_RE.findall(text) if _is_command_path(p, facts.code)]
    names += _SHELL_NOT_FOUND_RE.findall(text)
    names += [n for n in _WHICH_RE.findall(facts.code) if n in manifest.COMMAND_ALTERNATIVES]
    installed = set(manifest.command_names())
    return [n for n in _unique(names) if n not in installed]


def _command_hints(facts: RunFacts, text: str) -> List[str]:
    if not facts.full_image:
        return []
    hints = []
    for name in _missing_commands(facts, text)[:2]:
        use = manifest.COMMAND_ALTERNATIVES.get(name)
        instead = f" Use {use} instead." if use else ""
        hints.append(f"`{name}` is not available.{instead} Available commands: {_commands()}.")
    return hints


def _is_workspace_path(path: str) -> bool:
    return path.startswith((f"{_JUPYTER_WORKSPACE}/", f"{_DAYTONA_WORKSPACE}/"))


def _state_hints(facts: RunFacts, text: str) -> List[str]:
    missing_files = [
        p
        for p in _NO_SUCH_FILE_RE.findall(text)
        if not _is_command_path(p, facts.code) and not _FONT_FILE_RE.search(p)
    ]
    in_tmp = [p for p in missing_files if p.startswith("/tmp/") and not _is_workspace_path(p)]
    elsewhere = [p for p in missing_files if p not in in_tmp]
    name_errors = _NAME_ERROR_RE.findall(text)
    hints = []
    if in_tmp:
        hints.append(
            "/tmp is not kept between calls; write files you need later to scratch/ (or deliverables to the "
            "workspace)."
        )
    if facts.session_new and (elsewhere or name_errors):
        hints.append(
            "session: new — files/variables from earlier calls are gone. Recreate them in this call, or pass "
            "earlier outputs via inputs=['A2', ...]."
        )
    elif facts.backend == "daytona" and name_errors:
        hints.append("Each call is a fresh interpreter: re-import and reload from files.")
    return hints


# -- 5. Timeout ------------------------------------------------------------------------------


def _timeout_hint(facts: RunFacts) -> Optional[str]:
    if not facts.timed_out:
        return None
    return (
        "Nothing from the interrupted work was saved unless it was written before the cap; split the work into "
        "chunks and write partial results to scratch/ as you go."
    )


def _larger_timeout_hint(facts: RunFacts) -> Optional[str]:
    if not facts.timed_out or facts.timeout >= facts.max_timeout:
        return None
    return (
        f"This call had {facts.timeout}s. If the job is long by nature (video, OCR of many pages, a big "
        f"conversion or install), rerun it with a larger `timeout` (up to {facts.max_timeout}s)."
    )


# -- 5b. Out of memory -------------------------------------------------------------------------

# A process killed by SIGKILL, which in the sandbox is the kernel's OOM killer:
# subprocess's messages, a return code the code printed, and the shell's report.
_KILLED_RE = re.compile(
    r"died with <Signals\.SIGKILL: 9>"
    r"|non-zero exit status (?:137|-9)\b"
    r"|\b(?:returncode|return code|rc|exit code|exit status)\s*[=:]?\s*(?:-9|137)\b"
    r"|^(?:.*:\s*\d+\s+)?Killed(?:\s{2,}.*)?$",
    re.MULTILINE,
)


def _out_of_memory(facts: RunFacts, text: str) -> bool:
    """True when the run, or a process it started, ran out of memory."""
    if facts.timed_out:
        return False  # the cap kills the run too; that is not memory
    result = facts.result
    if result.out_of_memory:
        return True
    name, _ = exception_of(result)
    if name and name.endswith("MemoryError"):
        return True
    return bool(_KILLED_RE.search(text))


def _memory_hint(facts: RunFacts, text: str) -> Optional[str]:
    if not _out_of_memory(facts, text):
        return None
    return (
        "Ran out of memory. Load less at once: read files in chunks (pandas chunksize, one page or frame at a "
        "time), downsample or lower the resolution, del large objects you no longer need, and write "
        "intermediate results to scratch/."
    )


# -- 7. The app's own URLs ---------------------------------------------------------------------

_URL_RE = re.compile(r"""https?://[^\s'"<>`)\]]+""")
_FETCH_FAILED_RE = re.compile(
    r"\b40[13]\b|Forbidden|Unauthorized|ConnectionError|Connection refused|Max retries exceeded|"
    r"NameResolutionError|Failed to resolve|Name or service not known|Temporary failure in name resolution|"
    r"URLError|RemoteDisconnected",
)


def _is_app_url(url: str, hosts: Tuple[str, ...]) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if "/api/artifacts/" in parts.path:
        return True
    if not host:
        return False
    return host in hosts or (port is not None and f"{host}:{port}" in hosts)


def _app_url_hint(facts: RunFacts, text: str) -> Optional[str]:
    hosts = tuple(h.lower() for h in facts.app_hosts)
    if not any(_is_app_url(url, hosts) for url in _URL_RE.findall(facts.code)):
        return None
    if not _FETCH_FAILED_RE.search(text):
        return None
    return (
        "Artifact/app URLs need the user's session and can't be downloaded in the sandbox. Pass the file as "
        "inputs=['A3'] and read inputs/<name>."
    )


# -- 8. Deliverables outside the workspace ---------------------------------------------------------

_ABSOLUTE_DELIVERABLE_RE = re.compile(
    r"""(['"])(/[^'"\n]*?\.(?:pdf|docx|xlsx|pptx|png|jpe?g|csv|html?|mp4|zip))\1""", re.IGNORECASE
)
_SYSTEM_DIRS = ("/usr/", "/opt/", "/etc/", "/proc/", "/sys/", "/dev/", "/bin/", "/lib/")
_READ_CALL_RE = re.compile(
    r"(?:read_\w+|load_workbook|Image\.open|imread|PdfReader|PdfFileReader|pdfplumber\.open|PdfDocument|"
    r"Document|Presentation|exists|isfile|getsize|stat)\(\s*$"
)
_OPEN_CALL_RE = re.compile(r"\bopen\(\s*$")
_OPEN_MODE_RE = re.compile(r"""\s*,\s*(?:mode\s*=\s*)?['"]([^'"]*)['"]""")


def _written_outside_paths(code: str) -> List[str]:
    """Return absolute deliverable paths the code writes outside the workspace (a conservative guess)."""
    paths = []
    for match in _ABSOLUTE_DELIVERABLE_RE.finditer(code):
        path = match.group(2)
        if _is_workspace_path(path) or path.startswith(_SYSTEM_DIRS):
            continue
        prefix = code[code.rfind("\n", 0, match.start()) + 1 : match.start()]
        if _READ_CALL_RE.search(prefix):
            continue
        if _OPEN_CALL_RE.search(prefix):
            mode = _OPEN_MODE_RE.match(code, match.end())
            if not mode or not set(mode.group(1)) & set("wax+"):
                continue
        paths.append(path)
    return _unique(paths)


def _outside_workspace_hint(facts: RunFacts) -> Optional[str]:
    if not facts.result.ok:
        return None
    saved = {str(a.get("filename") or "").rsplit("/", 1)[-1] for a in facts.artifacts}
    paths = [p for p in _written_outside_paths(facts.code) if p.rsplit("/", 1)[-1] not in saved][:2]
    if not paths:
        return None
    verb = "is" if len(paths) == 1 else "are"
    example = paths[0].rsplit("/", 1)[-1]
    return (
        f"{', '.join(paths)} {verb} outside the workspace and was NOT saved for the user. Save deliverables in "
        f"the workspace (e.g. `{example}`)."
    )


# -- 9. Previews saved for the user -------------------------------------------------------------------

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")
_PREVIEW_NAME_RE = re.compile(r"(?:^|[^a-z])(?:preview|test|tmp|temp|debug|check)(?:[^a-z]|$)", re.IGNORECASE)
_MAX_LISTED_NAMES = 8


def _preview_hint(facts: RunFacts) -> Optional[str]:
    names = [str(a.get("filename") or "") for a in facts.artifacts if a.get("filename")]
    images = [
        n
        for a, n in zip(facts.artifacts, names)
        if str(a.get("mime_type") or "").startswith("image/") or n.lower().endswith(_IMAGE_EXTENSIONS)
    ]
    if len(images) > 3:
        flagged = images
    else:
        flagged = [n for n in names if _PREVIEW_NAME_RE.search(n.rsplit("/", 1)[-1].rsplit(".", 1)[0])]
    if not flagged:
        return None
    listed = ", ".join(flagged[:_MAX_LISTED_NAMES]) + (", ..." if len(flagged) > _MAX_LISTED_NAMES else "")
    return f"Saved for the user: {listed}. Put previews/tests in scratch/ next time."


# -- 10. Fonts -------------------------------------------------------------------------------------------

_FONT_ERROR_RE = re.compile(r"TTFError|cannot open resource|Fontconfig error")
_POSTSCRIPT_OUTLINES_RE = re.compile(r"postscript outlines are not supported", re.IGNORECASE)
_FONT_PATH_RE = re.compile(r"""['"]([^'"\n]+\.(?:ttf|otf|ttc))['"]""", re.IGNORECASE)
_MISSING_GLYPH_RE = re.compile(r"Glyph \d+ .*missing from (?:current )?font")
_REGISTERS_FONT_RE = re.compile(r"registerFont|TTFont|UnicodeCIDFont")


def _has_non_latin_letters(text: str) -> bool:
    """True when ``text`` holds a letter outside Latin-1 and Latin Extended (which Helvetica covers)."""
    return any(ord(ch) > 0x24F and ch.isalpha() for ch in text)


def _font_hint(facts: RunFacts, text: str) -> Optional[str]:
    if not facts.full_image:
        return None
    installed = {f["path"] for f in manifest.FONTS}
    missing_path = bool(_NO_SUCH_FILE_RE.search(text)) and bool(_FONT_PATH_RE.search(text))
    if _POSTSCRIPT_OUTLINES_RE.search(text):
        paths = _FONT_PATH_RE.findall(text)
        font = paths[0] if paths else "That font"
        return (
            f"reportlab can't load {font}: it has PostScript (CFF) outlines. For CJK text write HTML and convert it "
            "with html-to-pdf, or use reportlab's UnicodeCIDFont('STSong-Light') (Chinese), "
            "UnicodeCIDFont('HeiseiMin-W3') (Japanese) or UnicodeCIDFont('HYSMyeongJo-Medium') (Korean)."
        )
    if _FONT_ERROR_RE.search(text) or missing_path:
        paths = _FONT_PATH_RE.findall(text) or [p for p in _FONT_PATH_RE.findall(facts.code) if p not in installed]
        path = paths[0] if paths else "That font"
        return f"Font {path} not found. Installed fonts: {manifest.font_table()}."
    if _MISSING_GLYPH_RE.search(text):
        return (
            "The font lacks glyphs for some characters (they render as boxes). Use an installed font that covers "
            f"the script: {manifest.font_table()}."
        )
    if (
        facts.result.ok
        and "reportlab" in facts.code
        and not _REGISTERS_FONT_RE.search(facts.code)
        and _has_non_latin_letters(facts.code)
    ):
        return (
            "reportlab's built-in fonts (Helvetica, Times, Courier) have no glyphs for non-Latin text, which "
            "renders as boxes. Write HTML and convert it with html-to-pdf (it embeds the fonts and shapes Arabic "
            "and Devanagari), or register a TTF with pdfmetrics.registerFont(TTFont(name, path)): "
            f"{manifest.font_table(reportlab=True)}."
        )
    return None


# -- 11. Silent run --------------------------------------------------------------------------------------


def _silent_hint(facts: RunFacts) -> Optional[str]:
    result = facts.result
    if not result.ok or not facts.capture or facts.artifacts or facts.charts_shown:
        return None
    if clean_output(result.stdout).strip() or clean_output(result.stderr).strip():
        return None
    return "No output. print() the results you need to see (a bare last expression is not shown)."


# -- Assembly -------------------------------------------------------------------------------------------


def fix_hints(facts: RunFacts) -> List[str]:
    """Return short fixes for the mistakes this run shows, most specific first.

    Args:
        facts: The run.

    Returns:
        At most ``MAX_HINTS`` one- or two-line hints; empty when nothing is recognized.
    """
    text = _text_of(facts.result)
    hints: List[Optional[str]] = [
        _larger_timeout_hint(facts),
        _timeout_hint(facts),
        _memory_hint(facts, text),
        _app_url_hint(facts, text),
        *_missing_module_hints(facts, text),
        _compiled_package_hint(text),
        *_command_hints(facts, text),
        *_state_hints(facts, text),
        _apt_hint(facts),
        _pip_hint(facts),
        _font_hint(facts, text),
        _outside_workspace_hint(facts),
        _preview_hint(facts),
        _silent_hint(facts),
    ]
    return _unique(h for h in hints if h)[:MAX_HINTS]


# -- 12. Repeated failures -------------------------------------------------------------------------------

REPEATED_FAILURE_HINT = "This failed the same way twice; change approach instead of retrying."


class FailureMemory:
    """The last failure of each sandbox session, to notice the same one twice in a row.

    A tool instance lives for one request, so the memory is process-wide and keyed
    by session id (the conversation or workflow run). It is bounded: the least
    recently used sessions are forgotten first. With several API processes a
    session's calls can land on different ones; a repeat is then missed, never
    invented.
    """

    def __init__(self, max_sessions: int = 1024) -> None:
        """Hold at most ``max_sessions`` sessions' last failure."""
        self._max = max(1, max_sessions)
        self._last: "OrderedDict[str, str]" = OrderedDict()
        self._lock = threading.Lock()

    def repeated(self, session_id: str, signature: Optional[str]) -> bool:
        """Record a run's outcome and say whether it failed exactly like the session's previous run.

        Args:
            session_id: The sandbox session.
            signature: ``error_signature`` of the run; None for a success, which clears the record.

        Returns:
            True when this failure has the same signature as the one just before it.
        """
        with self._lock:
            previous = self._last.pop(session_id, None)
            if signature is None:
                return False
            self._last[session_id] = signature
            while len(self._last) > self._max:
                self._last.popitem(last=False)
            return previous == signature
