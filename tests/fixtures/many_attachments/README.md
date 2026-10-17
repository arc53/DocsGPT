# Many-attachments fixtures

Synthetic test scenarios for turns that carry many attached files: invoices,
screenshots, spreadsheets, long PDFs, scans, archives, and `/v1` clients that
re-send their documents on every turn.

## Provenance

Everything here is synthetic. The scenarios copy only the *shape* of anonymized
production patterns: file counts, types, token sizes, languages, turn structure,
client behaviour and model window. No production content, names or identifiers
were used. Every person, company, address, parcel, tax ID, phone number and
amount is invented, and identifiers are all-zero placeholders such as
`0000000000000` and `XX-000`. Legal texts carry a "FIKTIVNO BESEDILO" header.

No generated files are committed. Tests write them to a temporary directory.

## Files

| File | Purpose |
|---|---|
| `scenarios.yaml` | One entry per scenario: model profile, capability variants, file groups, conversations/turns, and the expected outcome under the new design. The schema and the disposition vocabulary are documented at the top of the file. |
| `generate.py` | Deterministic (seeded) generator and scenario helpers. |
| `corpus.py` | Text templates (Indonesian invoices, Hindi/English rulebooks, Slovenian ordinances/contracts, biology exams, papers, logs, code) sized to a token target. |
| `v1_requests.py` | Builds `/v1/chat/completions` bodies for V1-01..V1-05, either as pasted `[Priloga …]` text or as base64 `file` / `image_url` parts. |

The smoke test is `tests/test_many_attachments_fixtures.py`.

## Generating

```bash
# small profile: every scenario, a few seconds, about 10 MB
python -m tests.fixtures.many_attachments.generate --out /tmp/ma
# production-shaped sizes (100k-450k-token PDFs, 200k-row CSVs, 400-page scans): minutes, hundreds of MB
python -m tests.fixtures.many_attachments.generate --out /tmp/ma --full RC-04 V1-02
python -m tests.fixtures.many_attachments.generate --list
```

Each scenario directory has the files under `<group>/<name>`, source text sidecars
under `_text/` (OCR-style noisy text for scans), and a `manifest.json` with each
file's key, mime, sha256, effective and full-size token/row targets, pages,
zip members, `duplicate_of` and ground-truth `facts` (invoice totals, screenshot
quotes, quiz answers, dues colours).

The `small` profile caps text at about 3k tokens per file, spreadsheets at 300 rows,
scans at 2 pages, and scales images to 40%. File counts, names, types,
duplicates and turn structure stay the same. `scenarios.yaml` always gives the
full-size targets.

Hindi PDFs need a Devanagari-capable TTF (macOS "Arial Unicode", Noto Sans
Devanagari, Lohit or FreeSans on Linux, or one set in `MANY_ATTACHMENTS_DEVANAGARI_FONT`).
Without one, the generator writes romanized Hindi and records
`devanagari_font: false` in the manifest.

## Using it from tests

```python
from tests.fixtures.many_attachments import generate as gen

scenario = gen.get_scenario("RC-04")
rows = gen.attachment_records(scenario)          # virtual rows at FULL size, no files written
for caps in gen.capability_matrix(scenario):     # tools+sandbox / tools only / no tools x vision x payload
    for conv in gen.conversations(scenario):
        for turn in conv:
            exp = gen.expectations_for(scenario, turn, caps)
            # exp["files"]: {"reports[3]": ["tool"], ...}; exp["props"]: {"max_partial": 1, ...}
            # compare with the planner's output via gen.disposition_matches(allowed, actual)

manifest = gen.generate_scenario("RC-01", tmp_path)  # real files (small profile)
```

A planner unit test usually needs only `attachment_records` and
`expectations_for`. The fixture dispositions are a superset of the planner's
`FileStatus` values; `gen.planner_statuses(allowed)` maps them. `image` and
`back_filled` map to `inline`, `unreadable` maps to `tool` or `not_included`,
and `duplicate` and `skipped` have no planner status: they are checked through
ref collapsing and the manifest note. Use the real files for parser, worker, dedupe and
end-to-end checks.

## Using it end to end

```python
from tests.fixtures.many_attachments import generate as gen, v1_requests as v1

gen.generate_scenario("V1-01", out, "full")
for step in v1.build_requests("V1-01", out, payload="file_parts"):
    # step: {"conversation", "turn", "step": user|tool_round|forced_final, "stateless", "body"}
    post("/v1/chat/completions", json=step["body"])  # thread the conversation id yourself
```

For web-chat scenarios, upload `manifest["conversations"][c][t]["attach"]` (keys
into `manifest["files"]`) in order, then send `prompt`. `uploading: N` means N
more files were still uploading when the message was sent.

## Scenarios

| Id | Shape |
|---|---|
| RC-01 | 60 one-page Indonesian invoice PDFs (4 image-only scans, 3 exact re-sent duplicates) in 1/5/15/18/7 batches, 2 still uploading, then a follow-up with no files. |
| RC-02 | 50 phone screenshots (jpg/png/webp) with quotes, 5-10 per turn over 5 conversations, plus one `.heic` and one truncated PNG. |
| RC-03 | 4 coursework bundles: docx briefs, multi-sheet xlsx with formulas (5k-50k rows), CSV (1k-200k rows), Colab HTML exports (30k-180k tok), one pptx. One 17-file send with 2 uploading. |
| RC-04 | 32 biology exam PDFs (half with figures) + 2 duplicates + 12 examiners' reports of 128k-454k tokens in one agent turn with a vague prompt. |
| RC-05 | 29 papers with explicit sizes (a 120-page thesis that does not fit, smaller papers back-filled after it), 6 uploading, 4 follow-up turns with no files. |
| RC-06 | Hindi textbooks (12k-73k) and Hindi/English rulebooks (181k, 215k) over 3 conversations, for partial inline and chapter reads. |
| RC-07 | 36 phone photos (rotated or blurred) + a long template, a follow-up without images, then 1 more photo. |
| RC-08 | 120 quiz screenshots, one per turn, then 6 turns with no image (image-history cap). |
| RC-09 | 28 messy-header portfolio xlsx (30-400 rows, shared placeholder securities), 4 still uploading. |
| RC-10 | Club finances: bank statements (2 scanned), 12 short docx, colour-coded dues xlsx, a receipt photo, a follow-up 2 weeks later. |
| RC-11 | Zip of a 40-file Next.js app, zip of 25 markdown docs, mixed zip (nested zip plus an unsupported `.bin`), 7 logs of 300k-500k tokens, a script and a screenshot. |
| RC-12 | 3 image-only 400-page books, a 130k-token XML dump with an `.xlsm`/`.xlsx` pair, two 150k-token epubs, and 37 course PDFs with 2 transcripts. |
| V1-01 | Stateful legal client re-sends every file every turn (110k-token ordinance, contracts, certificate, OCR scans, 45k statute). The last turn re-sends everything twice. Text and file-part payloads. |
| V1-02 | A 260k-token ordinance + a 150k-token amendment as file parts + 10 image-only zoning-map PNGs. |
| V1-03 | 4 `PRILOGA_n.PDF` (upper-case) file parts, replayed through 3 client tool rounds. |
| V1-04 | V1-01 files, 4 client `search`/`get_by_id` rounds with statute excerpts, then a forced-final message (no tools) re-attaching all 8 files. |
| V1-05 | Stateless classifier: the same contract in 20 calls, each with a different extract (700-14k tokens). No system message, no tools, not streamed. |
