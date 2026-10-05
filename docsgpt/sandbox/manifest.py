"""What the code sandbox image holds: one manifest for the Daytona snapshot and the self-hosted runner.

Both sandbox backends run model-written code against the same set of
libraries, command-line tools and fonts, and the ``code_executor`` tool tells
the model what that set is. Everything that describes it lives here:

* ``scripts/build_daytona_snapshot.py`` builds the Daytona snapshot from it.
* ``scripts/export_sandbox_manifest.py`` writes the files the runner's
  Dockerfile installs from (``deployment/sandbox/requirements.txt``,
  ``install-system.sh``, ``sandbox.env`` and ``manifest.json``); a test fails
  when they are stale.
* ``CodeExecutorTool._environment_note`` renders ``preinstalled_summary()``.

The module is pure data plus small renderers and imports only the stdlib, so
the export script and CI load it without installing the backend.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Mapping, Optional, Tuple, TypedDict

# A pip package: exact pin, the name code imports it by, and what it is for.
PipPackage = TypedDict("PipPackage", {"spec": str, "import": str, "use": str})


class AptPackage(TypedDict):
    """A Debian package installed into the image."""

    name: str
    use: str


class Binary(TypedDict):
    """A command the image provides; ``on_path`` is False when it is reached another way."""

    name: str
    use: str
    on_path: bool


class Font(TypedDict):
    """A font family, the scripts it covers, and the file code can load it from."""

    name: str
    scripts: str
    path: str


class NodeRelease(TypedDict):
    """A pinned Node.js release with the SHA-256 of each Linux tarball."""

    version: str
    url: str
    sha256: Dict[str, str]


# Libraries baked into both images. Pins are exact so a rebuild gives the same
# image; pdfplumber stays at 0.11.9 because 0.11.10 needs Pillow >= 12.2.
PIP_PACKAGES: Tuple[PipPackage, ...] = (
    {"spec": "pandas==2.2.3", "import": "pandas", "use": "dataframes, CSV and Excel I/O"},
    {"spec": "numpy==2.1.3", "import": "numpy", "use": "arrays and maths"},
    {"spec": "matplotlib==3.9.2", "import": "matplotlib", "use": "charts"},
    {"spec": "openpyxl==3.1.5", "import": "openpyxl", "use": "Excel .xlsx"},
    {"spec": "python-docx==1.1.2", "import": "docx", "use": "Word .docx"},
    {"spec": "python-pptx==1.0.2", "import": "pptx", "use": "PowerPoint .pptx"},
    {"spec": "reportlab==4.2.5", "import": "reportlab", "use": "PDF generation"},
    {"spec": "lxml==6.0.2", "import": "lxml", "use": "XML and HTML parsing"},
    {"spec": "pillow==11.3.0", "import": "PIL", "use": "images"},
    {"spec": "requests==2.34.2", "import": "requests", "use": "HTTP"},
    {"spec": "beautifulsoup4==4.15.0", "import": "bs4", "use": "HTML parsing"},
    {"spec": "PyYAML==6.0.3", "import": "yaml", "use": "YAML"},
    {"spec": "pypdf==6.18.1", "import": "pypdf", "use": "read, merge and split PDFs"},
    {"spec": "PyPDF2==3.0.1", "import": "PyPDF2", "use": "older pypdf API that existing code imports"},
    {"spec": "pdfplumber==0.11.9", "import": "pdfplumber", "use": "PDF text, tables and page images"},
    {"spec": "pdfminer.six==20251230", "import": "pdfminer", "use": "PDF text layout (pdfplumber's engine)"},
    {"spec": "pypdfium2==5.13.0", "import": "pypdfium2", "use": "render PDF pages to images"},
    {"spec": "pytesseract==0.3.13", "import": "pytesseract", "use": "OCR through the tesseract binary"},
    {"spec": "imageio==2.38.0", "import": "imageio", "use": "animated GIF, WebP and PNG (MP4: the ffmpeg command)"},
)

# Runner plumbing: the self-hosted image runs a Jupyter Kernel Gateway. Daytona
# runs code through its own process API and does not need these.
RUNNER_PIP_PACKAGES: Tuple[PipPackage, ...] = (
    {"spec": "jupyter-kernel-gateway==3.0.1", "import": "kernel_gateway", "use": "the runner's gateway"},
    {"spec": "ipykernel==6.29.5", "import": "ipykernel", "use": "the runner's Python kernels"},
)

# Package names exist on Debian 12 (bookworm, the Daytona base) and Debian 13
# (trixie, the runner's python:3.12-slim base).
APT_PACKAGES: Tuple[AptPackage, ...] = (
    {"name": "ca-certificates", "use": "TLS roots for curl and the Node download"},
    {"name": "curl", "use": "downloads (the Node tarball at build time)"},
    {"name": "xz-utils", "use": "unpacks the Node tarball"},
    {"name": "fontconfig", "use": "font lookup for LibreOffice, Chromium and matplotlib"},
    {"name": "tesseract-ocr", "use": "OCR engine"},
    {"name": "tesseract-ocr-eng", "use": "English OCR model"},
    {"name": "poppler-utils", "use": "pdftotext, pdftoppm, pdfinfo"},
    {"name": "ffmpeg", "use": "ffmpeg and ffprobe for video and audio (Debian's build)"},
    {"name": "libreoffice-writer-nogui", "use": "headless LibreOffice Writer (docx, odt)"},
    {"name": "libreoffice-calc-nogui", "use": "headless LibreOffice Calc (xlsx, ods, csv)"},
    {"name": "libreoffice-impress-nogui", "use": "headless LibreOffice Impress (pptx, odp)"},
    {"name": "chromium-headless-shell", "use": "headless Chromium for HTML to PDF and screenshots"},
    {"name": "fonts-dejavu-core", "use": "DejaVu fonts"},
    {"name": "fonts-liberation2", "use": "Liberation fonts (Arial, Times New Roman, Courier New metrics)"},
    {"name": "fonts-crosextra-carlito", "use": "Carlito (Calibri metrics)"},
    {"name": "fonts-crosextra-caladea", "use": "Caladea (Cambria metrics)"},
    {"name": "fonts-noto-core", "use": "Noto fonts for Arabic, Devanagari, Hebrew, Thai and more"},
    {"name": "fonts-noto-cjk", "use": "Noto CJK fonts for Chinese, Japanese and Korean"},
)

# Node.js LTS from the official nodejs.org tarball. The hashes are copied from
# the release's signed SHASUMS256.txt; the build checks against them and never
# fetches a checksum file. To bump: pick the new v24.x, copy both linux-*.tar.xz
# lines from https://nodejs.org/dist/v<version>/SHASUMS256.txt (verify its
# signature), and re-run scripts/export_sandbox_manifest.py.
NODE: NodeRelease = {
    "version": "24.21.0",
    "url": "https://nodejs.org/dist/v{version}/node-v{version}-linux-{arch}.tar.xz",
    "sha256": {
        "amd64": "fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6",
        "arm64": "6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2",
    },
}

# Debian architecture -> the name nodejs.org uses in its tarball file names.
_NODE_ARCH = {"amd64": "x64", "arm64": "arm64"}

# Set for code running in the sandbox. tesseract uses OpenMP; one thread keeps a
# few OCR calls from fighting over the sandbox's CPUs. IMAGEIO_FFMPEG_EXE points
# imageio-ffmpeg, if code pip-installs it, at Debian's ffmpeg instead of the
# static build bundled in its wheel.
ENV: Dict[str, str] = {
    "PIP_ROOT_USER_ACTION": "ignore",
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "OMP_THREAD_LIMIT": "1",
    "IMAGEIO_FFMPEG_EXE": "/usr/bin/ffmpeg",
}

# Small commands baked into the image so common conversions work on the first
# try. Name -> source file under deployment/sandbox/.
HELPERS: Dict[str, str] = {
    "office-convert": "helpers/office_convert.py",
    "html-to-pdf": "helpers/html_render.py",
    "html-screenshot": "helpers/html_render.py",
}

BINARIES: Tuple[Binary, ...] = (
    {
        "name": "office-convert",
        "use": "office-convert FILE --to pdf|docx|xlsx|pptx|png [--outdir DIR] (LibreOffice)",
        "on_path": True,
    },
    {"name": "html-to-pdf", "use": "html-to-pdf IN.html|URL OUT.pdf (headless Chromium)", "on_path": True},
    {
        "name": "html-screenshot",
        "use": "html-screenshot IN.html|URL OUT.png [--width W --height H]",
        "on_path": True,
    },
    {"name": "soffice", "use": "LibreOffice", "on_path": True},
    {"name": "chromium-headless-shell", "use": "headless Chromium", "on_path": True},
    {"name": "tesseract", "use": "OCR", "on_path": True},
    {"name": "pdftotext", "use": "PDF to text (poppler)", "on_path": True},
    {"name": "pdftoppm", "use": "PDF pages to images (poppler)", "on_path": True},
    {"name": "node", "use": "Node.js", "on_path": True},
    {"name": "npm", "use": "Node package manager", "on_path": True},
    {"name": "npx", "use": "run npm package binaries", "on_path": True},
    {"name": "ffmpeg", "use": "video and audio encoding (call it with subprocess)", "on_path": True},
    {"name": "ffprobe", "use": "inspect video and audio files", "on_path": True},
)

FONTS: Tuple[Font, ...] = (
    {
        "name": "DejaVu Sans",
        "scripts": "Latin, Greek, Cyrillic",
        "path": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    },
    {
        "name": "Liberation Sans/Serif/Mono",
        "scripts": "Latin, Greek, Cyrillic; Arial, Times New Roman and Courier New metrics",
        "path": "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    },
    {
        "name": "Carlito",
        "scripts": "Latin; Calibri metrics",
        "path": "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    },
    {
        "name": "Caladea",
        "scripts": "Latin; Cambria metrics",
        "path": "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
    },
    {
        "name": "Noto Sans Arabic",
        "scripts": "Arabic, Persian, Urdu",
        "path": "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    },
    {
        "name": "Noto Sans Devanagari",
        "scripts": "Devanagari: Hindi, Marathi, Nepali",
        "path": "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
    },
    {
        "name": "Noto Sans CJK",
        "scripts": "Chinese, Japanese, Korean",
        "path": "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    },
)

_USE_FFMPEG_CLI = "not installed; run the ffmpeg command with subprocess for video, or write GIF/WebP with imageio"

# Import names models try that the image deliberately lacks, with what to use
# instead. Data for error hints; nothing here is installed.
NOT_INSTALLED: Dict[str, str] = {
    "fitz": "PyMuPDF is not installed (AGPL); use pdfplumber (text, tables, page images) or pypdf",
    "pymupdf": "PyMuPDF is not installed (AGPL); use pdfplumber (text, tables, page images) or pypdf",
    "pdf2image": "use pypdfium2 or pdfplumber's page.to_image(), or the pdftoppm command",
    "camelot": "use pdfplumber's page.extract_tables()",
    "tabula": "use pdfplumber's page.extract_tables()",
    "docx2pdf": "use the office-convert command: office-convert FILE.docx --to pdf",
    "comtypes": "use the office-convert command (LibreOffice) for Office conversions",
    "win32com": "use the office-convert command (LibreOffice) for Office conversions",
    "pdfkit": "use the html-to-pdf command (headless Chromium)",
    "weasyprint": "use the html-to-pdf command (headless Chromium)",
    "playwright": "use the html-to-pdf or html-screenshot command (headless Chromium)",
    "pyppeteer": "use the html-to-pdf or html-screenshot command (headless Chromium)",
    "selenium": "use the html-to-pdf or html-screenshot command (headless Chromium)",
    "moviepy": _USE_FFMPEG_CLI,
    "imageio_ffmpeg": _USE_FFMPEG_CLI,
    "av": _USE_FFMPEG_CLI,
    "cv2": "use Pillow or imageio; pip install opencv-python-headless if OpenCV itself is needed",
}

# Files scripts/export_sandbox_manifest.py writes, relative to the repository root.
GENERATED_DIR = "deployment/sandbox"

_GENERATED_HEADER = "GENERATED by scripts/export_sandbox_manifest.py from docsgpt/sandbox/manifest.py -- do not edit."
_ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")
_ENV_VALUE_RE = re.compile(r"[A-Za-z0-9_./:-]*")


def dist_name(spec: str) -> str:
    """Return the distribution name of an exact pin such as ``pandas==2.2.3``.

    Args:
        spec: A ``name==version`` requirement.

    Returns:
        The part before ``==``.
    """
    return spec.split("==", 1)[0]


def pip_specs(include_runner: bool = False) -> Tuple[str, ...]:
    """Return the pinned pip requirements, in manifest order.

    Args:
        include_runner: Also return the runner's gateway packages.

    Returns:
        The specs, sandbox libraries first.
    """
    packages = PIP_PACKAGES + (RUNNER_PIP_PACKAGES if include_runner else ())
    return tuple(p["spec"] for p in packages)


def apt_package_names() -> Tuple[str, ...]:
    """Return the Debian package names, in manifest order."""
    return tuple(p["name"] for p in APT_PACKAGES)


def node_url(arch: str) -> str:
    """Return the pinned Node.js tarball URL for a Debian architecture.

    Args:
        arch: ``amd64`` or ``arm64`` (``dpkg --print-architecture``).

    Returns:
        The nodejs.org download URL.

    Raises:
        ValueError: When no build is pinned for ``arch``.
    """
    if arch not in _NODE_ARCH or arch not in NODE["sha256"]:
        raise ValueError(f"no Node.js build pinned for {arch!r}")
    return NODE["url"].format(version=NODE["version"], arch=_NODE_ARCH[arch])


# fontconfig rule (one printf argument per line) that hides the liberation2
# compatibility link from font listings.
_LIBERATION_LINK_CONF = " ".join(
    f"'{line}'"
    for line in (
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">',
        "<fontconfig><selectfont><rejectfont><glob>/usr/share/fonts/truetype/liberation2/*</glob>"
        "</rejectfont></selectfont></fontconfig>",
    )
)


def _node_install_commands() -> List[str]:
    """Shell commands that download, verify and unpack the pinned Node.js build into /usr/local."""
    cases = " ".join(
        f'{arch}) node_url="{node_url(arch)}"; node_sha="{NODE["sha256"][arch]}";;' for arch in sorted(NODE["sha256"])
    )
    return [
        'arch="$(dpkg --print-architecture)"',
        f'case "$arch" in {cases} *) echo "no Node.js build pinned for $arch" >&2; exit 1;; esac',
        'curl -fsSL --retry 3 -o /tmp/node.tar.xz "$node_url"',
        'echo "$node_sha  /tmp/node.tar.xz" | sha256sum -c -',
        "tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 --no-same-owner",
        "rm -f /tmp/node.tar.xz /usr/local/CHANGELOG.md /usr/local/README.md",
        "mkdir -p /usr/local/share/doc/node",
        "mv /usr/local/LICENSE /usr/local/share/doc/node/LICENSE",
        "node --version",
        "npm --version",
    ]


def system_install_commands() -> List[str]:
    """Return the root-run commands that install the system packages and Node.js.

    The same list is written to ``install-system.sh`` for the runner's
    Dockerfile and joined into one RUN line for the Daytona snapshot.

    Returns:
        Shell commands, each complete on its own.
    """
    return [
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get update",
        "apt-get install -y --no-install-recommends " + " ".join(apt_package_names()),
        "rm -rf /var/lib/apt/lists/*",
        # Debian 12 ships Liberation 2 under liberation2/, Debian 13 under
        # liberation/; link the other name so one documented path works on both,
        # and keep fontconfig from listing every Liberation font twice.
        "if [ -d /usr/share/fonts/truetype/liberation ] && [ ! -e /usr/share/fonts/truetype/liberation2 ]; "
        "then ln -s liberation /usr/share/fonts/truetype/liberation2"
        f" && printf '%s\\n' {_LIBERATION_LINK_CONF} > /etc/fonts/conf.d/99-docsgpt-liberation2-link.conf; fi",
        "fc-cache -f",
        *_node_install_commands(),
    ]


def install_system_one_liner() -> str:
    """Return ``system_install_commands()`` joined into one shell line that stops at the first failure."""
    return " && ".join(system_install_commands())


def render_install_system_script() -> str:
    """Return ``install-system.sh``: the system install as a script the runner's Dockerfile runs as root."""
    body = "\n".join(system_install_commands())
    return (
        "#!/bin/sh\n"
        f"# {_GENERATED_HEADER}\n"
        "#\n"
        "# Installs the sandbox's Debian packages and the pinned Node.js build (checked\n"
        "# against the SHA-256 in the manifest). The Daytona snapshot runs the same commands.\n"
        "set -eu\n"
        f"{body}\n"
    )


def render_requirements() -> str:
    """Return ``requirements.txt`` for the runner image: the sandbox libraries, then the gateway."""
    return (
        f"# {_GENERATED_HEADER}\n"
        "# Sandbox libraries (also in the Daytona snapshot), then the runner's gateway packages.\n"
        + "".join(f"{spec}\n" for spec in pip_specs(include_runner=True))
    )


def render_env_file(env: Optional[Mapping[str, str]] = None) -> str:
    """Return ``sandbox.env``: the variables ``kernel-env.sh`` passes to kernel code.

    Args:
        env: Variables to render; defaults to ``ENV``.

    Returns:
        One ``NAME=value`` line per variable.

    Raises:
        ValueError: When a name or value could be misread by the shell script that loads the file.
    """
    env = ENV if env is None else env
    lines = [f"# {_GENERATED_HEADER}"]
    for name, value in env.items():
        if not _ENV_NAME_RE.fullmatch(name) or not _ENV_VALUE_RE.fullmatch(value):
            raise ValueError(f"unsafe sandbox env entry: {name}={value!r}")
        lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def render_manifest_json() -> str:
    """Return ``manifest.json``: the manifest as data for the smoke test inside the image."""
    data = {
        "generated": _GENERATED_HEADER,
        "pip": list(PIP_PACKAGES),
        "runner_pip": list(RUNNER_PIP_PACKAGES),
        "apt": list(APT_PACKAGES),
        "node": NODE,
        "env": ENV,
        "binaries": list(BINARIES),
        "fonts": list(FONTS),
        "helpers": HELPERS,
    }
    return json.dumps(data, indent=2) + "\n"


def generated_files() -> Dict[str, str]:
    """Return every generated file's path (relative to the repository root) and content."""
    return {
        f"{GENERATED_DIR}/requirements.txt": render_requirements(),
        f"{GENERATED_DIR}/install-system.sh": render_install_system_script(),
        f"{GENERATED_DIR}/sandbox.env": render_env_file(),
        f"{GENERATED_DIR}/manifest.json": render_manifest_json(),
    }


def _pip_label(pkg: PipPackage) -> str:
    """Name a package by its pip name, adding the import name when code imports it differently."""
    name = dist_name(pkg["spec"])
    if name.lower().replace("-", "_") == pkg["import"].lower():
        return name
    return f"{name} (import {pkg['import']})"


def preinstalled_summary() -> str:
    """Describe the image for the model: libraries with import names, commands and fonts.

    Returns:
        A few sentences listing what is installed.
    """
    packages = ", ".join(_pip_label(p) for p in PIP_PACKAGES)
    commands = "; ".join(
        [b["use"] if b["name"] in HELPERS else b["name"] for b in BINARIES if b["on_path"]]
        + [b["use"] for b in BINARIES if not b["on_path"]]
    )
    fonts = "; ".join(f"{f['name']} ({f['scripts']}) {f['path']}" for f in FONTS)
    return (
        f"Preinstalled Python packages beyond the stdlib: {packages}. "
        f"Commands: {commands}. "
        "For video run ffmpeg with subprocess; imageio writes GIF and WebP but has no MP4 writer here. "
        f"Fonts: {fonts}."
    )
