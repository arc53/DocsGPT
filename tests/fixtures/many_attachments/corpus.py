"""Deterministic synthetic text for the many-attachments fixtures.

Every name, company, address, identifier and figure produced here is invented.
Identifiers are placeholders made of zeros (``0000000000000``, ``XX-000``) so
nothing can be mistaken for a real record. Text is built from small template
vocabularies and sized to a target token count, so a planner test can rely on
"roughly N tokens" without depending on any real document.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

_COUNTER: Optional[Callable[[str], int]] = None


def count_tokens(text: str) -> int:
    """Count tokens the way the backend does (cl100k_base), with fallbacks.

    Args:
        text: The text to measure.

    Returns:
        The token count. Uses ``docsgpt.utils.num_tokens_from_string`` when the
        package imports, then plain ``tiktoken``, then a chars/4 estimate.
    """
    global _COUNTER
    if _COUNTER is None:
        try:
            from docsgpt.utils import num_tokens_from_string

            num_tokens_from_string("probe")
            _COUNTER = num_tokens_from_string
        except Exception:  # noqa: BLE001 - any import/setup failure falls back
            try:
                import tiktoken

                enc = tiktoken.get_encoding("cl100k_base")
                _COUNTER = lambda s: len(enc.encode_ordinary(s))  # noqa: E731
            except Exception:  # noqa: BLE001
                _COUNTER = lambda s: max(1, len(s) // 4)  # noqa: E731
    return _COUNTER(text)


def fill_to_tokens(make_unit: Callable[[int], str], target: int, sep: str = "\n") -> str:
    """Concatenate generated units until the token total reaches ``target``.

    Args:
        make_unit: Called with a running index, returns the next unit of text.
        target: Desired token count of the result.
        sep: Separator placed between units.

    Returns:
        Text whose token count is within a few tokens of ``target`` (units are
        counted one by one, so merges at the separators are the only drift).
    """
    parts: List[str] = []
    total = 0
    i = 0
    while total < target:
        unit = make_unit(i)
        size = count_tokens(unit) + 1
        # Stop short when adding the unit would overshoot by more than it
        # undershoots, so many small sections do not accumulate drift.
        if parts and total + size - target > target - total:
            break
        parts.append(unit)
        total += size
        i += 1
    return sep.join(parts)


# ---------------------------------------------------------------------------
# Indonesian invoices (RC-01)
# ---------------------------------------------------------------------------

ID_STORES = [
    "Toko Contoh Jaya",
    "PT Contoh Bunga",
    "CV Sampel Makmur",
    "Warung Fiktif Sejahtera",
    "Toko Teladan Abadi",
    "PT Ilustrasi Sentosa",
    "Apotek Contoh Sehat",
    "Minimarket Sampel 24",
]
ID_ITEMS = [
    ("Beras premium 5 kg", 72000),
    ("Minyak goreng 2 L", 38500),
    ("Gula pasir 1 kg", 17500),
    ("Kopi bubuk 200 g", 24000),
    ("Teh celup isi 25", 9800),
    ("Sabun cuci piring", 14200),
    ("Air mineral 600 ml (dus)", 52000),
    ("Kertas HVS A4 (rim)", 56000),
    ("Tinta printer hitam", 87000),
    ("Mi instan (dus)", 115000),
    ("Telur ayam 1 kg", 29000),
    ("Susu UHT 1 L", 19500),
    ("Pulpen biru (pak)", 21000),
    ("Lampu LED 12 W", 33000),
    ("Kabel roll 5 m", 64000),
]
ID_MONTHS = [
    "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember",
]


def rupiah(value: int) -> str:
    """Format an integer as Indonesian rupiah (``Rp 1.234.500``)."""
    return "Rp " + f"{value:,}".replace(",", ".")


def make_invoice(rng: random.Random, index: int, target_tokens: int) -> Tuple[List[str], Dict]:
    """Build one fictional Indonesian retail invoice.

    Args:
        rng: Seeded random source.
        index: Invoice ordinal, used in the invoice number.
        target_tokens: Rough size; drives the number of line items and notes.

    Returns:
        ``(lines, facts)`` where ``facts`` is the ground truth a correct
        extraction should return (number, date, store, total).
    """
    store = rng.choice(ID_STORES)
    day, month, year = rng.randint(1, 28), rng.randint(1, 12), 2026
    number = f"INV/{year}/{month:02d}/{index:04d}"
    date = f"{day} {ID_MONTHS[month - 1]} {year}"
    n_items = max(3, min(10, target_tokens // 70))
    items = rng.sample(ID_ITEMS, k=min(n_items, len(ID_ITEMS)))
    lines = [
        store.upper(),
        "Jl. Contoh No. 00, Kota Fiktif 00000 | Telp. 0000-0000-0000",
        "NPWP: 00.000.000.0-000.000",
        "",
        "FAKTUR PENJUALAN",
        f"No. Faktur: {number}",
        f"Tanggal: {date}",
        "Pelanggan: Pelanggan Umum (fiktif)",
        "",
        "No  Deskripsi                         Qty   Harga Satuan     Jumlah",
    ]
    total = 0
    for i, (name, price) in enumerate(items, start=1):
        qty = rng.randint(1, 6)
        amount = qty * price
        total += amount
        lines.append(f"{i:<3} {name:<33} {qty:>3}   {rupiah(price):>13}   {rupiah(amount):>13}")
    discount = rng.choice([0, 0, 5000, 10000])
    tax = round((total - discount) * 0.11)
    grand = total - discount + tax
    lines += [
        "",
        f"Subtotal: {rupiah(total)}",
        f"Diskon: {rupiah(discount)}",
        f"PPN 11%: {rupiah(tax)}",
        f"TOTAL: {rupiah(grand)}",
        "",
        "Pembayaran: " + rng.choice(["Tunai", "Transfer bank", "QRIS", "Kartu debit"]),
    ]
    filler = [
        "Barang yang sudah dibeli tidak dapat dikembalikan kecuali ada perjanjian.",
        "Simpan faktur ini sebagai bukti pembayaran yang sah.",
        "Keluhan dapat disampaikan paling lambat 7 hari setelah tanggal faktur.",
        "Dokumen ini dibuat secara elektronik dan sah tanpa tanda tangan.",
    ]
    text = "\n".join(lines)
    k = 0
    while count_tokens(text) < target_tokens * 0.9 and k < 40:
        lines.append(filler[k % len(filler)])
        text = "\n".join(lines)
        k += 1
    lines.append("Terima kasih atas kunjungan Anda.")
    facts = {"number": number, "date": date, "store": store, "total": rupiah(grand), "items": len(items)}
    return lines, facts


# ---------------------------------------------------------------------------
# Quotes / quizzes / photos (RC-02, RC-07, RC-08)
# ---------------------------------------------------------------------------

_QUOTE_SUBJECTS = ["A good map", "Patience", "Every small habit", "A quiet morning", "The second draft",
                   "Curiosity", "A shared table", "The long road", "An honest question", "Practice"]
_QUOTE_VERBS = ["teaches", "outlasts", "is worth more than", "slowly becomes", "quietly reveals",
                "makes room for", "begins with", "is kinder than"]
_QUOTE_OBJECTS = ["a hundred loud promises", "the plan you never wrote down", "the view from the summit",
                  "what we fear to lose", "every shortcut", "the answer we expected", "a perfect start",
                  "the noise of the crowd"]
_QUOTE_AUTHORS = ["R. Contoh", "M. Example", "J. Primer", "A. Sample", "L. Placeholder", "T. Vzorec"]


def make_quote(rng: random.Random) -> Dict[str, str]:
    """Return an invented aphorism attributed to a placeholder author."""
    text = f"{rng.choice(_QUOTE_SUBJECTS)} {rng.choice(_QUOTE_VERBS)} {rng.choice(_QUOTE_OBJECTS)}."
    return {"text": text, "author": rng.choice(_QUOTE_AUTHORS)}


_QUIZ_TOPICS = [
    ("Which organelle releases energy from glucose?", ["Ribosome", "Mitochondrion", "Vacuole", "Cell wall"], 1),
    ("What is 15% of 240?", ["24", "30", "36", "40"], 2),
    ("Which gas do plants absorb for photosynthesis?", ["Oxygen", "Nitrogen", "Carbon dioxide", "Helium"], 2),
    ("Which unit measures electrical resistance?", ["Volt", "Ohm", "Ampere", "Watt"], 1),
    ("What is the next prime after 13?", ["15", "17", "19", "21"], 1),
    ("Which layer of the Earth is liquid?", ["Crust", "Mantle", "Outer core", "Inner core"], 2),
    ("A triangle's angles sum to how many degrees?", ["90", "180", "270", "360"], 1),
    ("Which blood cells fight infection?", ["Red cells", "Platelets", "White cells", "Plasma"], 2),
]


def make_quiz(rng: random.Random, index: int) -> Dict:
    """Return a multiple-choice question with its correct option letter."""
    q, options, answer = _QUIZ_TOPICS[index % len(_QUIZ_TOPICS)]
    return {"question": f"Q{index + 1}. {q}", "options": options, "answer": "ABCD"[answer]}


PHOTO_SUBJECTS = ["notice board", "slide on a projector", "equipment label", "site visit", "whiteboard notes",
                  "safety poster", "machine panel", "warehouse shelf"]


# ---------------------------------------------------------------------------
# Generic English prose (papers, reports, logs, notebooks, write-ups)
# ---------------------------------------------------------------------------

_EN_SUBJ = ["The proposed method", "The control group", "The prototype", "Each sample", "The pilot study",
            "The regression model", "Most candidates", "The baseline configuration", "The survey panel",
            "The heat exchanger", "The cleaned dataset", "The team"]
_EN_VERB = ["reduced", "increased", "did not change", "stabilised", "outperformed", "matched", "underestimated",
            "explained", "confirmed", "contradicted"]
_EN_OBJ = ["the measured pressure drop", "the error rate", "the response time", "the expected yield",
           "the variance between runs", "the marks awarded in part (b)", "the seasonal trend",
           "the retention figure", "the reported limitation", "the earlier estimate"]
_EN_TAIL = ["under the stated assumptions", "across all three sites", "when the sample was reweighted",
            "in the second year of data", "compared with the reference case", "within the tolerance band",
            "after outliers were removed", "for the smaller configuration"]


def en_sentence(rng: random.Random) -> str:
    """Return one plausible but meaningless English sentence."""
    pct = rng.randint(2, 48)
    return (f"{rng.choice(_EN_SUBJ)} {rng.choice(_EN_VERB)} {rng.choice(_EN_OBJ)} by {pct}% "
            f"{rng.choice(_EN_TAIL)}.")


def en_paragraph(rng: random.Random, sentences: Tuple[int, int] = (4, 8)) -> str:
    """Return a paragraph of ``en_sentence`` output."""
    return " ".join(en_sentence(rng) for _ in range(rng.randint(*sentences)))


def paper_sections(rng: random.Random, title: str, target_tokens: int) -> List[Tuple[str, str]]:
    """Build an academic-paper-shaped list of ``(heading, body)`` sections."""
    heads = ["Abstract", "1. Introduction", "2. Research question", "3. Method", "4. Data",
             "5. Results", "6. Discussion", "7. Limitations", "8. Conclusion"]
    per = max(60, target_tokens // len(heads))
    out = [(title, "A. Example, B. Sample (fictional authors) - Institute of Placeholder Engineering")]
    for h in heads:
        out.append((h, fill_to_tokens(lambda i: en_paragraph(rng), per, sep="\n\n")))
    return out


# ---------------------------------------------------------------------------
# Biology exam papers and examiners' reports (RC-04)
# ---------------------------------------------------------------------------

_BIO_TOPICS = ["cell structure", "enzymes", "photosynthesis", "respiration", "inheritance", "ecosystems",
               "the heart and circulation", "osmosis", "the nervous system", "classification"]


def exam_questions(rng: random.Random, paper_no: int, target_tokens: int) -> List[str]:
    """Return question lines for a fictional biology exam paper."""
    lines = [f"FICTIONAL EXAMINATIONS BOARD - Biology Paper {paper_no}",
             "Candidate number: 0000   Centre number: XX-000", "Answer ALL questions. Time: 1 hour 30 minutes", ""]
    q = 1
    while count_tokens("\n".join(lines)) < target_tokens:
        topic = rng.choice(_BIO_TOPICS)
        lines.append(f"Question {q} ({topic})")
        lines.append(f"(a) Figure {q} shows a diagram related to {topic}. Name the structures labelled A and B. [2]")
        lines.append(f"(b) Explain how {topic} is affected when temperature rises by {rng.randint(5, 30)} C. [4]")
        lines.append(f"(c) {en_sentence(rng)} Suggest one reason for this observation. [3]")
        lines.append("")
        q += 1
    return lines


def examiner_report_paragraph(rng: random.Random, year: int, q: int) -> str:
    """Return one paragraph of a fictional examiners' report."""
    return (f"{year} Question {q}: " + en_paragraph(rng, (3, 6)) +
            f" Common errors included confusing {rng.choice(_BIO_TOPICS)} with {rng.choice(_BIO_TOPICS)}."
            f" Around {rng.randint(10, 90)}% of candidates gained full marks.")


# ---------------------------------------------------------------------------
# Hindi / English rulebooks and study notes (RC-06)
# ---------------------------------------------------------------------------

_HI_SUBJ = [("खिलाड़ी", "khiladi"), ("कप्तान", "kaptan"), ("निर्णायक", "nirnayak"), ("टीम", "team"),
            ("प्रशिक्षक", "prashikshak"), ("आयोजक", "aayojak")]
_HI_ACT = [("मैदान में प्रवेश से पहले पंजीकरण", "maidan mein pravesh se pehle panjikaran"),
           ("निर्धारित वर्दी पहनना", "nirdharit vardi pehenna"),
           ("खेल शुरू होने से पहले उपकरण की जाँच", "khel shuru hone se pehle upkaran ki jaanch"),
           ("समय पर उपस्थित होना", "samay par upasthit hona"),
           ("अंक तालिका पर हस्ताक्षर", "ank talika par hastakshar")]
_HI_PEN = [("चेतावनी", "chetavani"), ("दो अंकों की कटौती", "do ankon ki katauti"),
           ("एक मैच का निलंबन", "ek match ka nilamban"), ("जुर्माना", "jurmana")]


def hindi_rule(rng: random.Random, chapter: int, n: int, script: str = "deva") -> str:
    """Return one rule sentence of a fictional sport ("Gendball") in Hindi.

    Args:
        rng: Seeded random source.
        chapter: Chapter number used in the rule id.
        n: Rule number within the chapter.
        script: ``"deva"`` for Devanagari, ``"latn"`` for a romanized fallback
            (used when no Devanagari-capable font is installed).
    """
    idx = 0 if script == "deva" else 1
    s, a, p = rng.choice(_HI_SUBJ)[idx], rng.choice(_HI_ACT)[idx], rng.choice(_HI_PEN)[idx]
    if script == "deva":
        return f"नियम {chapter}.{n}: {s} को {a} अनिवार्य है, अन्यथा {p} दी जाएगी।"
    return f"Niyam {chapter}.{n}: {s} ko {a} anivarya hai, anyatha {p} di jayegi."


def rulebook_chapters(rng: random.Random, target_tokens: int, chapters: int, lang: str,
                      script: str = "deva") -> List[Tuple[str, str]]:
    """Return ``(heading, body)`` chapters of a fictional bilingual rulebook.

    Args:
        rng: Seeded random source.
        target_tokens: Total size of all chapters.
        chapters: Number of chapters.
        lang: ``"hi"`` (Hindi only), ``"en"`` or ``"hi-en"`` (alternating).
        script: Devanagari or romanized Hindi, see ``hindi_rule``.
    """
    per = max(80, target_tokens // chapters)
    out = []
    for c in range(1, chapters + 1):
        use_hi = lang == "hi" or (lang == "hi-en" and c % 2 == 1)
        if use_hi:
            head = (f"अध्याय {c} / Chapter {c}" if script == "deva" else f"Adhyay {c} / Chapter {c}")
            body = fill_to_tokens(lambda i, c=c: hindi_rule(rng, c, i + 1, script), per)
        else:
            head = f"Chapter {c}: Rules of play (fictional Gendball Federation)"
            body = fill_to_tokens(lambda i, c=c: f"Rule {c}.{i + 1}. " + en_sentence(rng), per)
        out.append((head, body))
    return out


# ---------------------------------------------------------------------------
# Slovenian legal set (V1-01..V1-05)
# ---------------------------------------------------------------------------

SL_HEADER = "FIKTIVNO BESEDILO ZA TESTIRANJE - NI VELJAVEN PRAVNI AKT"
SL_PARTIES = {
    "seller": "Janez Primer, EMŠO 0000000000000, davčna št. 00000000, Vzorčna ulica 0, 0000 Primerjevo",
    "buyer": "Podjetje Vzorec d.o.o., matična št. 0000000000, ID za DDV SI00000000, Testna cesta 00, 0000 Primerjevo",
    "lessee": "Marija Zgled, EMŠO 0000000000000, davčna št. 00000000, Pod Fikcijo 0, 0000 Vzorčna vas",
    "broker": "Nepremičnine Ilustracija d.o.o., matična št. 0000000000, Namišljena ulica 0, 0000 Primerjevo",
}
SL_PARCELS = ["parc. št. 0000/1, k.o. 0000 Vzorčna vas", "parc. št. 0000/2, k.o. 0000 Vzorčna vas",
              "parc. št. 0000/3, k.o. 0000 Primerjevo"]
_SL_ZONES = ["SSm", "SSs", "SK", "IG", "ZS", "CU", "K1", "G"]
_SL_ZONE_NAMES = {"SSm": "površine eno- in dvostanovanjskih stavb", "SSs": "površine večstanovanjskih stavb",
                  "SK": "površine podeželskega naselja", "IG": "gospodarske cone", "ZS": "površine za oddih",
                  "CU": "osrednja območja centralnih dejavnosti", "K1": "najboljša kmetijska zemljišča",
                  "G": "gozdna zemljišča"}
_SL_SUBJ = ["V enoti urejanja prostora", "Na območju z namensko rabo", "Znotraj gradbene meje v enoti",
            "Na zemljiščih v enoti"]
_SL_RULE = ["so dopustne novogradnje, rekonstrukcije in odstranitve objektov",
            "je dopustna gradnja enostanovanjskih in dvostanovanjskih stavb",
            "faktor zazidanosti parcele ne sme presegati 0,4",
            "višina objektov je omejena na P+1+M",
            "je treba zagotoviti najmanj dve parkirni mesti na stanovanje",
            "streha mora biti dvokapnica z naklonom od 35 do 45 stopinj",
            "odmik od sosednjih zemljišč mora znašati najmanj 4,0 m",
            "niso dopustni objekti za intenzivno rejo živali"]


def sl_article(rng: random.Random, n: int) -> str:
    """Return one invented article (``člen``) of a fictional municipal ordinance."""
    zone = rng.choice(_SL_ZONES)
    eup = f"PR-{rng.randint(1, 99):02d}"
    paras = [f"{n}. člen", f"({_SL_ZONE_NAMES[zone]} - {zone})"]
    for k in range(1, rng.randint(2, 5) + 1):
        paras.append(f"({k}) {rng.choice(_SL_SUBJ)} {eup} ({zone}) {rng.choice(_SL_RULE)}.")
    return "\n".join(paras)


def sl_ordinance(rng: random.Random, title: str, target_tokens: int) -> str:
    """Return a fictional Slovenian ordinance/statute of roughly ``target_tokens``."""
    head = f"{SL_HEADER}\n\n{title}\n\nI. SPLOŠNE DOLOČBE\n"
    body = fill_to_tokens(lambda i: sl_article(rng, i + 1), max(50, target_tokens - count_tokens(head)),
                          sep="\n\n")
    return head + body


def sl_contract(rng: random.Random, kind: str, target_tokens: int) -> str:
    """Return a fictional Slovenian sale / lease / brokerage contract.

    Args:
        rng: Seeded random source.
        kind: ``"prodajna"``, ``"najemna"`` or ``"posredniska"``.
        target_tokens: Approximate size.
    """
    title = {"prodajna": "PRODAJNA POGODBA", "najemna": "NAJEMNA POGODBA",
             "posredniska": "POSREDNIŠKA POGODBA"}[kind]
    a = SL_PARTIES["seller"]
    b = SL_PARTIES["lessee" if kind == "najemna" else "buyer"]
    if kind == "posredniska":
        b = SL_PARTIES["broker"]
    price = rng.randint(50, 900) * 1000
    head = (f"{SL_HEADER}\n\n{title}\n\nki jo skleneta:\n1. {a} (v nadaljevanju: prva pogodbena stranka)\n"
            f"2. {b} (v nadaljevanju: druga pogodbena stranka)\n\n"
            f"Predmet pogodbe je nepremičnina {rng.choice(SL_PARCELS)}, v izmeri {rng.randint(300, 2500)} m2.\n"
            f"Dogovorjena kupnina oziroma najemnina znaša {price:,} EUR.\n".replace(",", "."))
    clauses = ["Prva pogodbena stranka jamči, da je nepremičnina bremen prosta.",
               "Stroške overitve podpisov nosi druga pogodbena stranka.",
               "Morebitne spore rešuje stvarno pristojno sodišče v Primerjevem.",
               "Pogodba je sestavljena v štirih enakih izvodih.",
               "Izročitev nepremičnine se opravi v roku 30 dni po plačilu celotne kupnine.",
               "Zemljiškoknjižno dovolilo se izda po prejemu celotne kupnine."]

    def unit(i: int) -> str:
        return f"{i + 1}. člen\n" + " ".join(rng.choice(clauses) for _ in range(rng.randint(2, 4)))

    return head + "\n" + fill_to_tokens(unit, max(50, target_tokens - count_tokens(head)), sep="\n\n")


def sl_location_certificate(rng: random.Random, target_tokens: int) -> str:
    """Return a fictional location-information certificate (lokacijska informacija)."""
    zone = rng.choice(["SSm", "SK"])
    head = (f"{SL_HEADER}\n\nOBČINA PRIMERJEVO (fiktivna)\nLOKACIJSKA INFORMACIJA št. XX-000/2026\n\n"
            f"Zemljišče: {SL_PARCELS[0]}\nNamenska raba: {zone} - {_SL_ZONE_NAMES[zone]}\n"
            f"Enota urejanja prostora: PR-{rng.randint(1, 99):02d}\n")
    return head + fill_to_tokens(lambda i: f"{i + 1}. {rng.choice(_SL_RULE).capitalize()}.",
                                 max(30, target_tokens - count_tokens(head)))


def ocr_noise(rng: random.Random, text: str, rate: float = 0.04) -> str:
    """Return ``text`` with OCR-style character noise (substitutions, drops)."""
    swaps = {"č": "c", "š": "s", "ž": "z", "l": "1", "O": "0", "e": "c", "m": "rn", "i": "í"}
    out = []
    for ch in text:
        r = rng.random()
        if r < rate / 2 and ch in swaps:
            out.append(swaps[ch])
        elif r < rate * 0.6 and ch == " ":
            continue
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Archives and logs (RC-11, RC-12)
# ---------------------------------------------------------------------------


def log_line(rng: random.Random, i: int) -> str:
    """Return one line of a fictional service log."""
    level = rng.choice(["INFO", "INFO", "INFO", "WARN", "DEBUG", "ERROR"])
    svc = rng.choice(["ingest", "billing", "scheduler", "api", "cache"])
    return (f"2026-01-{(i // 50000) % 28 + 1:02d}T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z "
            f"{level} {svc} req=XX-{rng.randint(0, 999):03d} " + en_sentence(rng))


def ts_component(rng: random.Random, name: str, target_tokens: int) -> str:
    """Return a fictional React/TypeScript component source file."""
    head = (f"import React from 'react';\n\ntype {name}Props = {{ title: string; items: string[] }};\n\n"
            f"export default function {name}({{ title, items }}: {name}Props) {{\n  return (\n"
            f"    <section className=\"{name.lower()}\">\n      <h2>{{title}}</h2>\n      <ul>\n")

    def unit(i: int) -> str:
        return f"        <li key=\"{i}\">{{items[{i}] ?? '{en_sentence(rng)[:40]}'}}</li>"

    return head + fill_to_tokens(unit, max(20, target_tokens - 60)) + "\n      </ul>\n    </section>\n  );\n}\n"


def markdown_doc(rng: random.Random, title: str, target_tokens: int) -> str:
    """Return a fictional markdown documentation page."""
    def unit(i: int) -> str:
        if i % 4 == 0:
            return f"\n## Section {i // 4 + 1}\n"
        if i % 4 == 3:
            return "```bash\nexample-cli run --config ./example.yaml\n```"
        return en_paragraph(rng, (2, 4))

    return f"# {title}\n\n" + fill_to_tokens(unit, target_tokens)


def xml_config_line(rng: random.Random, i: int) -> str:
    """Return one ``<param>`` line of a fictional network-vendor config dump."""
    return (f"  <param id=\"P{i:06d}\" node=\"XX-{rng.randint(0, 999):03d}\" name=\"cell.{rng.choice(['tx', 'rx', 'hoa', 'qos'])}"
            f".{rng.randint(0, 99)}\" value=\"{rng.randint(-120, 120)}\" unit=\"{rng.choice(['dBm', 'ms', '%'])}\"/>")
