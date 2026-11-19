#!/bin/bash -eu
# Package each tests/fuzz/fuzz_*.py harness into a fuzzer binary in $OUT.
# compile_python_fuzzer (from the OSS-Fuzz base image) runs PyInstaller; the
# cl100k ranks file is data, so it is bundled where docsgpt.utils looks for it.

cd "$SRC/docsgpt"
for fuzzer in tests/fuzz/fuzz_*.py; do
  compile_python_fuzzer "$fuzzer" \
    --paths "$SRC/docsgpt" \
    --add-data "docsgpt/core/encodings/cl100k_base.tiktoken:docsgpt/core/encodings"
done
