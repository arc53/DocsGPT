# Fuzz harnesses

Coverage-guided [atheris](https://github.com/google/atheris) harnesses for
backend code that parses untrusted input. Each one checks invariants, not just
"does not crash":

| Harness | Target | Checks |
| --- | --- | --- |
| `fuzz_safe_url.py` | `docsgpt.security.safe_url` (SSRF guard) | an accepted URL never reaches a loopback/private/link-local/CGNAT/metadata address, and urllib3 reads the same host the guard checked |
| `fuzz_zip_archive.py` | `docsgpt.security.zip_archive` | only `ZipExtractionError` escapes; a failed extraction leaves nothing behind; a successful one stays inside the destination and within its limits |
| `fuzz_origins.py` | `docsgpt.security.origins` | stored and request origins normalize to one fixed-point form |
| `fuzz_chunking.py` | `docsgpt.parser.tokenization`, chunkers | splitting is lossless and every chunk fits `max_tokens` |

They are not pytest tests (pytest collects `test_*.py` only).

## CI

[ClusterFuzzLite](https://google.github.io/clusterfuzzlite/) builds them from
`.clusterfuzzlite/` and runs them for a few minutes on pull requests that touch
`docsgpt/` (`.github/workflows/cflite-pr.yml`), and for longer once a day
(`.github/workflows/cflite-batch.yml`). A crash fails the job and the input that
caused it is uploaded as the `fuzz-crash` artifact.

## Running locally

atheris ships Linux wheels; on macOS it has to be built against a Clang with
libFuzzer (Homebrew `llvm`), so Linux or the CI image is easier.

```bash
python3.11 -m venv /tmp/fuzz-venv
/tmp/fuzz-venv/bin/pip install atheris
/tmp/fuzz-venv/bin/pip install --require-hashes -r tests/fuzz/requirements.txt
PYTHONPATH=. DOCSGPT_ENV_FILE= /tmp/fuzz-venv/bin/python tests/fuzz/fuzz_safe_url.py -max_total_time=60
```

Arguments after the script are libFuzzer flags (`-max_total_time`, `-runs`,
`-max_len`, a corpus directory). To replay a crash from CI, pass the downloaded
file: `python tests/fuzz/fuzz_safe_url.py crash-<sha>`.

To run exactly what CI runs, use the OSS-Fuzz helper from a checkout of
[google/oss-fuzz](https://github.com/google/oss-fuzz):

```bash
python infra/helper.py build_fuzzers --external /path/to/DocsGPT
python infra/helper.py run_fuzzer --external /path/to/DocsGPT fuzz_safe_url
```

## Dependencies

The fuzz image runs Python 3.11 (the OSS-Fuzz base image) and installs only
what the harnesses import, pinned to the versions in `docsgpt/requirements.txt`
and hashed. After adding an import to a harness, or after a lock bump you want
the fuzzers to follow, regenerate the file:

```bash
uv pip compile tests/fuzz/requirements.in -c docsgpt/requirements.txt \
  --generate-hashes --python-version 3.11 --python-platform x86_64-manylinux_2_28 \
  --no-header -o tests/fuzz/requirements.txt
```
