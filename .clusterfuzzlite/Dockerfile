# ClusterFuzzLite build image for the atheris harnesses in tests/fuzz/.
# The base image ships Python 3.11 with atheris and PyInstaller preinstalled.
FROM gcr.io/oss-fuzz-base/base-builder-python@sha256:21f6fab17ace4dc76e1c56de91ee95d3d03da021df94b41056ba036f6c6f55e9

# Only the packages the harnesses import, pinned by hash (see tests/fuzz/README.md).
COPY tests/fuzz/requirements.txt $SRC/fuzz-requirements.txt
RUN python3 -m pip install --no-cache-dir --require-hashes --only-binary :all: -r $SRC/fuzz-requirements.txt

COPY . $SRC/docsgpt
WORKDIR $SRC/docsgpt
COPY .clusterfuzzlite/build.sh $SRC/
