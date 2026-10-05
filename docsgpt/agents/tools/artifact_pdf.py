"""The ``pdf`` artifact renderer: reportlab with fonts that cover the text's scripts.

``artifact_generator`` sends this module's source to the sandbox and calls
``render_pdf_spec`` there, so the module imports only the standard library at
the top and reportlab, arabic_reshaper and python-bidi inside functions. The API
process imports it only in tests.

reportlab's built-in Helvetica draws Latin-1 and nothing else, so Cyrillic,
Greek, Arabic, Devanagari, CJK and symbols such as ``−`` or ``→`` used to come
out as boxes or blanks. Here:

* Fonts. DejaVu Sans is the base family. Every other script the text uses gets
  the Noto font the sandbox image installs; the table of files comes from
  ``PDF_FONTS`` in ``docsgpt/sandbox/manifest.py`` and is looked up here, in
  the sandbox. A base face missing from the image is taken from matplotlib's
  bundled DejaVu Sans, and with no DejaVu at all the base is Helvetica. A font
  that is missing or will not load is skipped, never fatal.
* Mixed scripts. Each character is drawn in the first font whose character map
  has it (its script's font, then the base, then the symbol fonts), and runs in
  a font other than the paragraph's are wrapped in ``<font name="...">``.
* Chinese, Japanese and Korean use reportlab's built-in CID fonts (STSong-Light,
  HeiseiKakuGo-W5, HYGothic-Medium), chosen per sentence: kana makes it
  Japanese, Hangul Korean, anything else Chinese. reportlab cannot load the
  Noto CJK collection (CFF outlines in a ``.ttc``), and a CID font needs no
  file: the PDF names the font and the viewer supplies the glyphs. They have no
  bold face.
* Right-to-left text. reportlab neither joins Arabic letters nor reorders RTL
  text. Arabic is reshaped into its presentation forms (arabic_reshaper), the
  paragraph is broken into lines here, each line is reordered for display
  (python-bidi, with bracket pairs mirrored) and the paragraph is right-aligned
  when its first strong character is right-to-left.
* Scripts that need shaping (Devanagari, Bengali, Tamil, Thai and the rest of
  ``SHAPED_SCRIPTS``) go through reportlab's HarfBuzz shaping when reportlab
  supports it and uharfbuzz is installed; without it, or in a paragraph where
  one word is drawn in two fonts, they draw unshaped.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import unicodedata
from importlib.util import find_spec
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

BASE_FAMILY = "ArtifactSans"

# Unicode blocks the renderer picks a font for, sorted by start and
# non-overlapping. Characters outside them (Latin, Greek, Cyrillic, Armenian,
# Georgian, digits, punctuation, symbols) have no script and go to the base
# font when it has them. "cjk" is CJK punctuation and full-width forms, drawn
# in the document's CJK font.
_SCRIPT_RANGES: Tuple[Tuple[int, int, str], ...] = (
    (0x0590, 0x05FF, "hebrew"),
    (0x0600, 0x06FF, "arabic"),
    (0x0700, 0x074F, "syriac"),
    (0x0750, 0x077F, "arabic"),
    (0x0870, 0x08FF, "arabic"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0A80, 0x0AFF, "gujarati"),
    (0x0B00, 0x0B7F, "oriya"),
    (0x0B80, 0x0BFF, "tamil"),
    (0x0C00, 0x0C7F, "telugu"),
    (0x0C80, 0x0CFF, "kannada"),
    (0x0D00, 0x0D7F, "malayalam"),
    (0x0D80, 0x0DFF, "sinhala"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1000, 0x109F, "myanmar"),
    (0x1100, 0x11FF, "hangul"),
    (0x1200, 0x139F, "ethiopic"),
    (0x1780, 0x17FF, "khmer"),
    (0x1CD0, 0x1CFF, "devanagari"),
    (0x2E80, 0x2FDF, "han"),
    (0x3000, 0x303F, "cjk"),
    (0x3040, 0x30FF, "kana"),
    (0x3130, 0x318F, "hangul"),
    (0x31F0, 0x31FF, "kana"),
    (0x3200, 0x33FF, "cjk"),
    (0x3400, 0x4DBF, "han"),
    (0x4E00, 0x9FFF, "han"),
    (0xA8E0, 0xA8FF, "devanagari"),
    (0xA960, 0xA97F, "hangul"),
    (0xAC00, 0xD7FF, "hangul"),
    (0xF900, 0xFAFF, "han"),
    (0xFB1D, 0xFB4F, "hebrew"),
    (0xFB50, 0xFDFF, "arabic"),
    (0xFE30, 0xFE4F, "cjk"),
    (0xFE70, 0xFEFF, "arabic"),
    (0xFF00, 0xFF65, "cjk"),
    (0xFF66, 0xFF9F, "kana"),
    (0xFFA0, 0xFFDF, "hangul"),
    (0xFFE0, 0xFFEF, "cjk"),
    (0x20000, 0x323AF, "han"),
)
_RANGE_STARTS = [start for start, _end, _script in _SCRIPT_RANGES]
# Punctuation inside a script block that other scripts share: the dandas end
# Bengali, Gurmukhi and Oriya sentences as well as Devanagari ones.
_SHARED_PUNCTUATION = frozenset({0x0964, 0x0965})
# Where a CJK sentence ends, for choosing its font.
_SENTENCE_END = frozenset("。！？.!?\n．")

RTL_SCRIPTS = frozenset({"arabic", "hebrew", "syriac"})
CJK_SCRIPTS = frozenset({"han", "kana", "hangul", "cjk"})
# Scripts whose letters change shape or order around each other, so they read
# correctly only after HarfBuzz shaping.
SHAPED_SCRIPTS = frozenset(
    {
        "devanagari", "bengali", "gurmukhi", "gujarati", "oriya", "tamil", "telugu",
        "kannada", "malayalam", "sinhala", "thai", "lao", "khmer", "myanmar",
    }
)
# reportlab's CID fonts per CJK flavour: no file, not embedded, drawn by the viewer.
CID_FONTS: Dict[str, str] = {"zh": "STSong-Light", "ja": "HeiseiKakuGo-W5", "ko": "HYGothic-Medium"}
# DejaVu Sans faces matplotlib bundles, the fallback when the image lacks a face
# (fonts-dejavu-core has no oblique).
_DEJAVU_FILES: Dict[str, str] = {
    "regular": "DejaVuSans.ttf",
    "bold": "DejaVuSans-Bold.ttf",
    "italic": "DejaVuSans-Oblique.ttf",
    "bold_italic": "DejaVuSans-BoldOblique.ttf",
}
_HELVETICA: Dict[str, str] = {
    "regular": "Helvetica",
    "bold": "Helvetica-Bold",
    "italic": "Helvetica-Oblique",
    "bold_italic": "Helvetica-BoldOblique",
}
# Bracket pairs python-bidi reorders but does not mirror.
_OPENING = {"(": ")", "[": "]", "{": "}", "«": "»", "‹": "›"}
_CLOSING = {close: open_ for open_, close in _OPENING.items()}
_PAGE_FRAME_PADDING = 12  # SimpleDocTemplate's frame pads 6pt on each side.
_WHITESPACE = re.compile(r"\s+")


def script_of(ch: str) -> Optional[str]:
    """Return the script key the renderer picks a font for, or None for base-font text.

    Args:
        ch: One character.

    Returns:
        ``"arabic"``, ``"devanagari"``, ``"han"``... from ``_SCRIPT_RANGES``,
        or None for Latin, Greek, Cyrillic, digits, punctuation and symbols.
    """
    code = ord(ch)
    if code < 0x0590 or code in _SHARED_PUNCTUATION:
        return None
    index = bisect.bisect_right(_RANGE_STARTS, code) - 1
    if index >= 0 and code <= _SCRIPT_RANGES[index][1]:
        return _SCRIPT_RANGES[index][2]
    return None


def detect_scripts(texts: Iterable[str]) -> Set[str]:
    """Return every script key used in ``texts``.

    Args:
        texts: The strings of a spec.

    Returns:
        The set of ``script_of`` keys found, without None.
    """
    found: Set[str] = set()
    for text in texts:
        for ch in text:
            script = script_of(ch)
            if script is not None:
                found.add(script)
    return found


def cjk_flavor(scripts: Set[str]) -> str:
    """Pick the CJK font for one sentence's Han characters and CJK punctuation.

    Kana means Japanese. Hangul without any Han ideograph means Korean. Anything
    else is drawn as Chinese: the Chinese CID font has every common Han
    character, while the Japanese one lacks simplified forms such as 报.

    Args:
        scripts: The sentence's ``detect_scripts`` result.

    Returns:
        ``"ja"``, ``"ko"`` or ``"zh"``: a key of ``CID_FONTS``.
    """
    if "kana" in scripts:
        return "ja"
    if "hangul" in scripts and "han" not in scripts:
        return "ko"
    return "zh"


def cjk_flavors(text: str) -> List[Optional[str]]:
    """Return, for each character of ``text``, the CJK font flavour of its sentence, or None outside CJK.

    Kana is always Japanese and Hangul always Korean; Han and CJK punctuation
    follow ``cjk_flavor`` of the sentence they are in, so a Chinese sentence
    next to a Japanese one keeps its simplified characters.
    """
    flavors: List[Optional[str]] = [None] * len(text)
    start = 0
    for end in range(len(text) + 1):
        if end < len(text) and text[end] not in _SENTENCE_END:
            continue
        sentence = text[start : end + 1]
        scripts = detect_scripts([sentence])
        if scripts & CJK_SCRIPTS:
            flavor = cjk_flavor(scripts)
            for index in range(start, min(end + 1, len(text))):
                script = script_of(text[index])
                if script in CJK_SCRIPTS:
                    flavors[index] = {"kana": "ja", "hangul": "ko"}.get(script, flavor)
        start = end + 1
    return flavors


def is_rtl(text: str) -> bool:
    """Return True when ``text`` holds any right-to-left character."""
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


def base_direction(text: str) -> str:
    """Return the paragraph direction, ``"R"`` or ``"L"``, from its first strong character (UAX #9 P2/P3)."""
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return "R"
        if kind == "L":
            return "L"
    return "L"


def all_text(spec: Mapping[str, Any]) -> List[str]:
    """Return the title and every block's text of a pdf spec, as strings."""
    texts = []
    if spec.get("title"):
        texts.append(str(spec["title"]))
    for block in spec.get("blocks") or []:
        if isinstance(block, dict):
            texts.append(str(block.get("text", "")))
    return texts


class FontSet:
    """The fonts registered for one document and which characters each can draw.

    Attributes:
        base: The base family's faces by role (``regular``, ``bold``,
            ``italic``, ``bold_italic``): ArtifactSans or Helvetica.
        scripts: Script key to its ``(regular, bold)`` TrueType font names.
        cjk: CJK flavour (``zh``, ``ja``, ``ko``) to its CID font name.
        fallbacks: Font names tried, in order, for characters neither the
            character's script font nor the base has (math and symbols).
        shaping: True when reportlab can shape text through HarfBuzz.
    """

    def __init__(self, base: Optional[Mapping[str, str]] = None) -> None:
        """Start with the base faces (Helvetica when not given) and no script fonts."""
        self.base: Dict[str, str] = dict(base or _HELVETICA)
        self.scripts: Dict[str, Tuple[str, str]] = {}
        self.cjk: Dict[str, str] = {}
        self.fallbacks: List[str] = []
        self.shaping = False
        self._coverage: Dict[str, Callable[[int], bool]] = {}
        for name in self.base.values():
            if name in _HELVETICA.values():
                self._coverage[name] = _latin1_covers

    def add_coverage(self, name: str, covers: Callable[[int], bool]) -> None:
        """Record which code points the font ``name`` can draw."""
        self._coverage[name] = covers

    def covers(self, name: str, ch: str) -> bool:
        """Return True when the font ``name`` has a glyph for ``ch``."""
        check = self._coverage.get(name)
        return bool(check and check(ord(ch)))

    def face(self, bold: bool = False, italic: bool = False) -> str:
        """Return the base family's face for the given weight and slant."""
        if bold:
            return self.base["bold_italic" if italic else "bold"]
        return self.base["italic" if italic else "regular"]

    def candidates(self, ch: str, bold: bool, flavor: Optional[str] = None) -> List[str]:
        """Return the fonts to try for ``ch``, best first: its script's font, the base, then the fallbacks.

        Args:
            ch: The character.
            bold: Use bold faces.
            flavor: For a CJK character, the ``cjk_flavors`` entry choosing its CID font.
        """
        names = []
        script = script_of(ch)
        if script in self.scripts:
            names.append(self.scripts[script][1 if bold else 0])
        elif script in CJK_SCRIPTS and self.cjk:
            names.append(self.cjk.get(flavor or "zh") or next(iter(self.cjk.values())))
        names.append(self.face(bold))
        names.extend(self.fallbacks)
        return names


def _latin1_covers(code: int) -> bool:
    """What a standard PDF font draws: printable WinAnsi (cp1252) characters."""
    try:
        chr(code).encode("cp1252")
    except UnicodeEncodeError:
        return False
    return code >= 0x20


def _first_existing(paths: Iterable[Optional[str]]) -> List[str]:
    """Return the given paths that are files, in order, without repeats."""
    seen: List[str] = []
    for path in paths:
        if path and path not in seen and os.path.isfile(path):
            seen.append(path)
    return seen


def _register_ttf(name: str, paths: Iterable[Optional[str]], fonts: FontSet, shapable: bool) -> Optional[str]:
    """Register the first of ``paths`` that reportlab loads under ``name``; return the name, or None."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for path in _first_existing(paths):
        free = _free_name(name, path)
        try:
            font = TTFont(free, path)
        except Exception:  # a CFF/OTF or broken file: try the next candidate
            continue
        pdfmetrics.registerFont(font)
        # reportlab keeps the first font registered for a face, so read coverage
        # from (and set shaping on) the object it actually draws with.
        registered = pdfmetrics.getFont(free)
        # reportlab >= 4.4 shapes through uharfbuzz when a font is shapable;
        # older versions ignore the attribute.
        registered.shapable = shapable
        fonts.add_coverage(free, registered.face.charToGlyph.__contains__)
        return free
    return None


def _free_name(name: str, path: str) -> str:
    """Return ``name``, or ``name-2``, ``name-3``...: the first not registered for a different file.

    The sandbox kernel lives across renders and reportlab ignores a second
    registration of a name, so a name already bound to another file is skipped.
    """
    from reportlab.pdfbase import pdfmetrics

    registered = set(pdfmetrics.getRegisteredFontNames())
    candidate, number = name, 1
    while candidate in registered:
        if getattr(pdfmetrics.getFont(candidate).face, "filename", None) == path:
            return candidate
        number += 1
        candidate = f"{name}-{number}"
    return candidate


def _register_family(regular: str, bold: str, italic: str, bold_italic: str) -> None:
    """Map a family's faces so ``<b>`` and ``<i>`` markup inside its paragraphs resolve."""
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    registerFontFamily(regular, normal=regular, bold=bold, italic=italic, boldItalic=bold_italic)


def matplotlib_font_dir() -> Optional[str]:
    """Return matplotlib's bundled TrueType directory without importing matplotlib, or None."""
    try:
        spec = find_spec("matplotlib")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    return os.path.join(os.path.dirname(spec.origin), "mpl-data", "fonts", "ttf")


def shaping_supported() -> bool:
    """Return True when reportlab can shape text: reportlab 4.4+ with uharfbuzz importable."""
    try:
        from reportlab.pdfbase import ttfonts
    except ImportError:
        return False
    return getattr(ttfonts, "uharfbuzz", None) is not None and hasattr(ttfonts, "shapeFragWord")


def load_fonts(
    table: Sequence[Mapping[str, str]],
    scripts: Set[str],
    font_dir: Optional[str] = None,
) -> FontSet:
    """Register the fonts a document needs and return them as a ``FontSet``.

    Args:
        table: ``PDF_FONTS`` from the sandbox manifest: ``{"script", "regular",
            "bold"}`` entries. ``"base"`` is the base family, ``"symbols"``
            entries are fallbacks in order, any other script key is that
            script's font.
        scripts: The scripts the document uses; only their fonts are loaded.
        font_dir: Where to look for the DejaVu faces the table lacks;
            matplotlib's bundled fonts by default.

    Returns:
        The registered fonts. Missing or unloadable files leave a role empty
        (or Helvetica for the base) instead of raising.
    """
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    shaping = shaping_supported()
    font_dir = matplotlib_font_dir() if font_dir is None else font_dir
    base_entry = next((entry for entry in table if entry.get("script") == "base"), {})
    base_dirs = [os.path.dirname(base_entry["regular"])] if base_entry.get("regular") else []
    base_dirs.append(font_dir)

    def base_paths(role: str) -> List[Optional[str]]:
        listed = base_entry.get(role) if role in ("regular", "bold") else None
        return [listed] + [os.path.join(d, _DEJAVU_FILES[role]) for d in base_dirs if d]

    fonts = FontSet()
    fonts.shaping = shaping
    regular = _register_ttf(BASE_FAMILY, base_paths("regular"), fonts, shaping)
    if regular:
        bold = _register_ttf(f"{BASE_FAMILY}-Bold", base_paths("bold"), fonts, shaping) or regular
        italic = _register_ttf(f"{BASE_FAMILY}-Italic", base_paths("italic"), fonts, shaping) or regular
        bold_italic = _register_ttf(f"{BASE_FAMILY}-BoldItalic", base_paths("bold_italic"), fonts, shaping) or bold
        fonts.base = {"regular": regular, "bold": bold, "italic": italic, "bold_italic": bold_italic}
        _register_family(regular, bold, italic, bold_italic)

    for entry in table:
        script = entry.get("script", "")
        if script not in scripts or script in fonts.scripts:
            continue
        name = f"{BASE_FAMILY}-{script}"
        shapable = shaping and script in SHAPED_SCRIPTS
        loaded = _register_ttf(name, [entry.get("regular")], fonts, shapable)
        if loaded:
            loaded_bold = _register_ttf(f"{name}-Bold", [entry.get("bold")], fonts, shapable) or loaded
            fonts.scripts[script] = (loaded, loaded_bold)
            _register_family(loaded, loaded_bold, loaded, loaded_bold)

    if scripts & CJK_SCRIPTS:
        # Which flavour a sentence takes is decided per sentence; a CID font
        # costs nothing until a run uses it, so all three are registered.
        for flavor, name in CID_FONTS.items():
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(UnicodeCIDFont(name))
                _register_family(name, name, name, name)
            fonts.add_coverage(name, _cid_covers)
            fonts.cjk[flavor] = name

    for number, entry in enumerate(e for e in table if e.get("script") == "symbols"):
        loaded = _register_ttf(f"{BASE_FAMILY}-symbols{number}", [entry.get("regular")], fonts, False)
        if loaded:
            fonts.fallbacks.append(loaded)
            _register_family(loaded, loaded, loaded, loaded)
    return fonts


def _cid_covers(code: int) -> bool:
    """What a CJK CID font draws: CJK text, its punctuation and printable ASCII."""
    return 0x20 <= code < 0x7F or script_of(chr(code)) in CJK_SCRIPTS


def font_runs(text: str, fonts: FontSet, bold: bool = False, italic: bool = False) -> List[Tuple[str, str]]:
    """Split ``text`` into runs that one font draws, each in the first font that has its characters.

    Letters go to their script's font, then the base, then the fallbacks.
    Spaces, digits, punctuation and marks stay in the run they follow (or the
    one they lead into) when its font has them, so a run does not break at
    every comma. Invisible format characters (ZWNJ, bidi marks) are dropped
    when the font they would join cannot draw them, instead of showing a box.

    Args:
        text: Paragraph text, in the order it will be drawn.
        fonts: The document's fonts.
        bold: Use bold faces.
        italic: Use the base family's italic face for base text.

    Returns:
        ``[(font_name, text), ...]`` with adjacent runs in different fonts.
    """
    base = fonts.face(bold, italic)
    flavors = cjk_flavors(text)
    picks: List[Optional[str]] = []
    for ch, flavor in zip(text, flavors):
        if _is_neutral(ch):
            picks.append(None)
            continue
        options = fonts.candidates(ch, bold, flavor)
        name = next((n for n in options if fonts.covers(n, ch)), options[0])
        picks.append(base if name == fonts.face(bold) else name)

    # The font of the next letter after each position, found in one backward pass.
    following: List[Optional[str]] = [None] * len(text)
    upcoming: Optional[str] = None
    for index in range(len(text) - 1, -1, -1):
        following[index] = upcoming
        if picks[index] is not None:
            upcoming = picks[index]

    runs: List[Tuple[str, str]] = []
    previous: Optional[str] = None
    for index, ch in enumerate(text):
        name = picks[index]
        if name is None:
            word_start = index == 0 or text[index - 1].isspace()
            name = _neutral_font(ch, previous, following[index], word_start, fonts, base)
            if name is None:
                continue
        previous = name
        if runs and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + ch)
        else:
            runs.append((name, ch))
    return runs


def _is_neutral(ch: str) -> bool:
    """Return True for characters that take the font of their neighbours: not letters, no script of their own."""
    if script_of(ch) is not None:
        return False
    return not unicodedata.category(ch).startswith("L")


def _neutral_font(
    ch: str, before: Optional[str], after: Optional[str], word_start: bool, fonts: FontSet, base: str
) -> Optional[str]:
    """Choose a font for a neutral character: a neighbour's, the base's or a fallback's.

    Args:
        ch: The neutral character.
        before: The font of the character drawn just before it, if any.
        after: The font of the next letter, if any.
        word_start: ``ch`` opens a word (follows whitespace or starts the text).
        fonts: The document's fonts.
        base: The paragraph's base face.

    Returns:
        A font name, or None to drop an invisible format character no font draws.
    """
    candidates = [before, after, base] + fonts.fallbacks
    if word_start and not ch.isspace():
        # Leading punctuation joins the word it opens, e.g. "(" before "हिन्दी".
        candidates = [after, before, base] + fonts.fallbacks
    for name in candidates:
        if name is not None and fonts.covers(name, ch):
            return name
    if unicodedata.category(ch) == "Cf":
        return None
    return before or base


def runs_markup(runs: Sequence[Tuple[str, str]], paragraph_font: str) -> str:
    """Return reportlab paragraph markup for ``runs``, escaping text and tagging fonts other than the paragraph's."""
    from xml.sax.saxutils import escape

    parts = []
    for name, chunk in runs:
        if name == paragraph_font:
            parts.append(escape(chunk))
        else:
            parts.append(f'<font name="{name}">{escape(chunk)}</font>')
    return "".join(parts)


def mirror_brackets(visual: str, direction: str) -> str:
    """Mirror the brackets python-bidi reversed without mirroring.

    In display order a right-to-left pair comes out closing bracket first,
    ``")word("``; such pairs are swapped. A bracket with no partner is mirrored
    when the line is right-to-left and its nearest strong neighbour is too.

    Args:
        visual: One line in display order.
        direction: The paragraph direction, ``"R"`` or ``"L"``.

    Returns:
        The line with those brackets mirrored.
    """
    chars = list(visual)
    stack: List[int] = []
    swap: Set[int] = set()
    paired: Set[int] = set()
    for index, ch in enumerate(chars):
        if ch not in _OPENING and ch not in _CLOSING:
            continue
        if stack:
            top = chars[stack[-1]]
            if ch in _CLOSING and top == _CLOSING[ch]:
                paired.update((stack.pop(), index))
                continue
            if ch in _OPENING and top == _OPENING[ch]:
                start = stack.pop()
                swap.update((start, index))
                paired.update((start, index))
                continue
        stack.append(index)
    if direction == "R":
        for index in stack:
            if index not in paired and _nearest_strong(chars, index) != "L":
                swap.add(index)
    for index in swap:
        ch = chars[index]
        chars[index] = _OPENING.get(ch) or _CLOSING[ch]
    return "".join(chars)


def _nearest_strong(chars: Sequence[str], index: int) -> Optional[str]:
    """Return ``"L"`` or ``"R"`` for the closest strong character to ``index``, or None."""
    for distance in range(1, len(chars)):
        for position in (index - distance, index + distance):
            if 0 <= position < len(chars):
                kind = unicodedata.bidirectional(chars[position])
                if kind == "L":
                    return "L"
                if kind in ("R", "AL"):
                    return "R"
    return None


def reshape_arabic(text: str) -> str:
    """Join Arabic letters into their presentation forms (arabic_reshaper); unchanged when it is missing."""
    try:
        import arabic_reshaper
    except ImportError:
        return text
    return arabic_reshaper.reshape(text)


def _bidi_display() -> Optional[Callable[..., str]]:
    """Return python-bidi's ``get_display``, or None when it is missing."""
    try:
        from bidi import get_display
    except ImportError:
        try:
            from bidi.algorithm import get_display
        except ImportError:
            return None
    return get_display


def break_lines(text: str, measure: Callable[[str], float], width: float) -> List[str]:
    """Break ``text`` into lines no wider than ``width``, at spaces, splitting words wider than a line.

    Args:
        text: Paragraph text in logical order.
        measure: Width of a string in points.
        width: The line width in points.

    Returns:
        The lines, in logical order, with runs of whitespace collapsed to one space.
    """
    lines: List[str] = []
    current = ""
    for word in _WHITESPACE.split(text.strip()):
        if not word:
            continue
        candidate = f"{current} {word}" if current else word
        if measure(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while len(word) > 1 and measure(word) > width:
            cut = _fitting_prefix(word, measure, width)
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def _fitting_prefix(word: str, measure: Callable[[str], float], width: float) -> int:
    """Return how many leading characters of ``word`` fit in ``width`` (at least one), adding widths one by one."""
    used = 0.0
    for count, ch in enumerate(word):
        used += measure(ch)
        if used > width:
            return max(count, 1)
    return len(word)


def rtl_markup(
    text: str, fonts: FontSet, font_size: float, width: float, bold: bool = False, italic: bool = False
) -> Tuple[str, str]:
    """Return markup for a paragraph holding right-to-left text, and its direction.

    The text is reshaped, broken into lines that fit ``width`` in logical
    order, and each line is reordered for display and mirrored, so reportlab
    lays out lines it does not need to wrap again.

    Args:
        text: Paragraph text in logical order.
        fonts: The document's fonts.
        font_size: The paragraph's font size in points.
        width: The width a line may take, in points.
        bold: Use bold faces.
        italic: Use the base family's italic face for base text.

    Returns:
        ``(markup, direction)``: lines joined with ``<br/>``, and ``"R"`` or ``"L"``.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    direction = base_direction(text)
    shaped = reshape_arabic(text)
    paragraph_font = fonts.face(bold, italic)

    def measure(chunk: str) -> float:
        return sum(stringWidth(part, name, font_size) for name, part in font_runs(chunk, fonts, bold, italic))

    display = _bidi_display()
    lines = []
    for line in break_lines(shaped, measure, width):
        if display is not None:
            line = mirror_brackets(display(line, base_dir=direction), direction)
        # Joining and reordering are done: ZWNJ and the bidi marks have no job
        # left, and Noto draws a visible bar for ZWNJ.
        line = strip_format_characters(line)
        lines.append(runs_markup(font_runs(line, fonts, bold, italic), paragraph_font))
    return "<br/>".join(lines), direction


def strip_format_characters(text: str) -> str:
    """Drop invisible format characters (ZWNJ, ZWJ, bidi marks, soft hyphens): unshaped text would draw them."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _one_font_per_word(runs: Sequence[Tuple[str, str]]) -> bool:
    """Return True when no space-separated word is drawn in two fonts.

    reportlab shapes a word with the font of its first run, so a word whose
    runs use different fonts would be drawn with the wrong glyphs.
    """
    word_font: Optional[str] = None
    for name, chunk in runs:
        for ch in chunk:
            if ch.isspace():
                word_font = None
            elif word_font is None:
                word_font = name
            elif word_font != name:
                return False
    return True


def paragraph_for(text: str, style: Any, fonts: FontSet, width: float, bold: bool, italic: bool = False) -> Any:
    """Build the reportlab Paragraph for one block of text in ``style``.

    Args:
        text: The block's text.
        style: The reportlab ParagraphStyle to start from.
        fonts: The document's fonts.
        width: The frame width a line may take, in points.
        bold: The style draws bold.
        italic: The style draws italic.

    Returns:
        A Paragraph: right-aligned with pre-broken lines for right-to-left
        text, CJK line breaking for CJK text, HarfBuzz shaping for scripts that
        need it.
    """
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph

    text = unicodedata.normalize("NFC", text)
    paragraph_font = fonts.face(bold, italic)
    scripts = detect_scripts([text])
    if is_rtl(text):
        markup, direction = rtl_markup(text, fonts, style.fontSize, width * 0.98, bold, italic)
        if direction == "R" and style.alignment == TA_LEFT:
            style = ParagraphStyle(f"{style.name}-rtl", parent=style, alignment=TA_RIGHT)
        return Paragraph(markup, style)

    plain = runs_markup(font_runs(strip_format_characters(text), fonts, bold, italic), paragraph_font)
    if scripts & CJK_SCRIPTS:
        return Paragraph(plain, ParagraphStyle(f"{style.name}-cjk", parent=style, wordWrap="CJK"))
    if fonts.shaping and scripts & SHAPED_SCRIPTS:
        # HarfBuzz uses ZWJ and ZWNJ to choose conjuncts, so shaped text keeps them.
        runs = font_runs(text, fonts, bold, italic)
        if _one_font_per_word(runs):
            shaped_style = ParagraphStyle(f"{style.name}-shaped", parent=style)
            shaped_style.shaping = 1
            paragraph = Paragraph(runs_markup(runs, paragraph_font), shaped_style)
            try:
                paragraph.wrap(width, 10_000)
            except Exception:  # a shaping failure must not cost the document: draw it unshaped
                return Paragraph(plain, style)
            return paragraph
    return Paragraph(plain, style)


def build_styles(fonts: FontSet) -> Dict[str, Tuple[Any, bool, bool]]:
    """Return the sample stylesheet's styles the renderer uses, pointed at the document's base family.

    Args:
        fonts: The document's fonts.

    Returns:
        ``{name: (style, bold, italic)}`` for Title, Heading1 to Heading3,
        BodyText, Normal and Bullet.
    """
    from reportlab.lib.styles import getSampleStyleSheet

    sheet = getSampleStyleSheet()
    faces = {
        "Title": (True, False),
        "Heading1": (True, False),
        "Heading2": (True, False),
        "Heading3": (True, True),
        "BodyText": (False, False),
        "Normal": (False, False),
        "Bullet": (False, False),
    }
    styles = {}
    for name, (bold, italic) in faces.items():
        style = sheet[name]
        style.fontName = fonts.face(bold, italic)
        styles[name] = (style, bold, italic)
    return styles


def render_pdf_spec(spec_path: str, out_path: str, font_table: Sequence[Mapping[str, str]] = ()) -> None:
    """Render a ``pdf`` artifact spec to ``out_path``.

    Args:
        spec_path: The spec JSON, read as data.
        out_path: Where to write the PDF.
        font_table: ``PDF_FONTS`` from the sandbox manifest.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Spacer

    with open(spec_path, encoding="utf-8") as handle:
        spec = json.load(handle)
    texts = [unicodedata.normalize("NFC", text) for text in all_text(spec)]
    fonts = load_fonts(font_table, detect_scripts(texts))
    styles = build_styles(fonts)
    doc = SimpleDocTemplate(out_path, pagesize=letter)
    width = doc.width - _PAGE_FRAME_PADDING

    def add(text: str, style_name: str, gap: float) -> None:
        style, bold, italic = styles[style_name]
        story.append(paragraph_for(text, style, fonts, width, bold, italic))
        story.append(Spacer(1, gap))

    story: List[Any] = []
    title = spec.get("title")
    if title:
        add(str(title), "Title", 12)
    for block in spec.get("blocks", []):
        if block.get("type") == "heading":
            try:
                level = int(block.get("level") or 1)
            except (TypeError, ValueError):
                level = 1
            style_name = "Heading%d" % min(max(level, 1), 3)
        else:
            style_name = "BodyText"
        add(str(block.get("text", "")), style_name, 6)
    doc.build(story)

