# arc_decide_onnx.py from https://huggingface.co/arc53/arc-decide-0.4b-v0.2
# at revision cb32fe9190a78aed4291fd8e8f087628dc5053df, vendored by docsgpt.decisions.
# Unchanged except that the imports from arc_decide are relative; tests/decisions/test_vendor.py
# checks it against the release file.
#
# MIT License
#
# Copyright (c) 2026 Arc53
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""CPU client for an arc-decide ONNX export (``scripts/onnx_export.py``): same API and outputs as ``arc_decide.py``.

Needs only ``onnxruntime``, ``tokenizers`` and ``numpy`` (plus ``huggingface_hub`` to fetch from the Hub), for hosts
without a GPU. The prompt, the heads and the answer shapes come from ``arc_decide.py``, which must sit next to this
file, so both clients build byte-identical prompts.

    from arc_decide_onnx import Decider
    d = Decider("arc53/arc-decide-0.4b-v0.2")   # or a local folder holding model.onnx
    d.decide({"query": "...", "passage": "..."}, {"relevant": {"type": "noul", "instructions": "..."}})

The graph returns logits for the label tokens only (``arcd_label_tokens`` in its metadata). As in the reference
client, the state is encoded once and every question runs on its KV cache. ``threads`` defaults to the cores the
process may actually use (its affinity, capped by a cgroup CPU v2 quota such as ``docker --cpus``): onnxruntime's
own default counts the host's cores, and in a 4-CPU container on a 48-CPU host that made a prescreen 5.8x slower.
Padded batches of states were not faster on CPU, so a prescreen is a loop over ``decide``.

Low-memory mode (the default) gives the same answers bit for bit with less peak memory: about 0.3 GB less for the
0.4B model's int8 file, which is what keeps every DocsGPT call shape within 1 GB, and 0.45-0.6 GB less for the 0.6B
model's fp32 file on long calls (little on a short single question). A plain onnxruntime run returns the KV cache as new arrays on every pass and copies
the past into them; this mode avoids that and bounds what each pass allocates:

- **One KV buffer per layer**, allocated once and bound through IOBinding as both the graph's ``past_key_values.*``
  input and its ``present.*`` output. GroupQueryAttention sees the same memory and appends the new rows in place.
  Each question forks the state by passing a shorter ``attention_mask`` (the graph derives the cached length from
  it), so its suffix overwrites the rows after the state.
- **A state with one question is one pass with every layer on the first layer's rows.** GroupQueryAttention writes
  a layer's keys and values and reads them in the same kernel, and layers run one after another, so each layer may
  overwrite the previous one's: the KV memory of one layer instead of all of them.
- **Prefill in passes of 256 tokens** (except that single pass), which bounds each pass's activations.
- **The buffer grows in steps of 1,024 rows** and is mapped lazily, so rows a call never reaches cost nothing.
- **An exact-size arena:** onnxruntime's CPU arena normally grows by doubling and keeps what it took. Here it grows by
  exactly what is requested and returns unused regions after every run. The CPU provider takes no arena options,
  so this is a process-wide shared allocator that this client's sessions opt into; other sessions are unaffected.

``low_memory=False`` runs the plain path (``session.run`` with the KV cache as outputs), as v0.1's client did. A
low-memory ``Decider`` owns one buffer, so its calls are serialised; use one per thread to run calls in parallel.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from .arc_decide import PROMPT_HASH, _softmax, prefix_text, suffix_text
from .arc_decide import Decider as _Reference

CHUNK = 256  # tokens per prefill pass in low-memory mode
ROUND_TO = 1024  # the KV buffer grows in steps of this many rows


class _Tokenizer:
    """The two calls the reference client makes on a transformers tokenizer, on the tokenizers library alone."""

    def __init__(self, path: Path):
        from tokenizers import Tokenizer

        self._tok = Tokenizer.from_file(str(path))

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return self._tok.encode(text, add_special_tokens=add_special_tokens).ids

    def decode(self, ids: list[int]) -> str:
        return self._tok.decode(ids, skip_special_tokens=False)


def cpu_budget() -> int:
    """Cores this process may use: its CPU affinity, capped by a cgroup v2 CPU quota."""
    n = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
    except (OSError, ValueError):
        return n
    return n if quota == "max" else max(1, min(n, int(quota) // int(period)))


def steps(n: int, start: int, chunk: int) -> list[tuple[int, int, int]]:
    """(begin, end, total length) of each pass that appends ``n`` ids after ``start`` cached ones; 0: one pass."""
    size = chunk or n
    return [(a, min(a + size, n), start + min(a + size, n)) for a in range(0, n, size)]


def capacity(needed: int, have: int, round_to: int = ROUND_TO) -> int:
    """Rows the KV buffer should hold: unchanged while ``needed`` fits, else ``needed`` rounded up."""
    return have if needed <= have else -(-needed // round_to) * round_to


_ARENA_REGISTERED = False


def exact_arena(ort) -> None:
    """Register, once per process, a shared CPU arena that grows by exactly what is requested (kSameAsRequested).
    Sessions use it only with ``session.use_env_allocators``."""
    global _ARENA_REGISTERED
    if _ARENA_REGISTERED:
        return
    info = ort.OrtMemoryInfo("Cpu", ort.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, ort.OrtMemType.DEFAULT)
    try:
        ort.create_and_register_allocator(info, ort.OrtArenaCfg({"arena_extend_strategy": 1}))
    except Exception as e:  # another copy of this module (or the host application) registered one first
        if "already" not in str(e).lower():
            raise
    _ARENA_REGISTERED = True


@contextlib.contextmanager
def _without_huge_pages():
    """numpy asks for transparent huge pages on arrays of 4 MB and more, which map 2 MB on each first write; the KV
    buffer should map only the rows a call writes."""
    core = getattr(np, "_core", None) or np.core
    hint = getattr(core.multiarray, "_set_madvise_hugepage", None)
    before = hint(False) if hint else None
    try:
        yield
    finally:
        if hint:
            hint(before)


class SharedKV:
    """The low-memory pass plan over one session: one KV buffer per layer, bound as both past and present."""

    def __init__(self, session, past_names: list[str], present_names: list[str], kv_shape: tuple[int, int],
                 ort_value: Callable[[np.ndarray], Any], run_options=None, chunk: int = CHUNK,
                 one_layer: bool = True, round_to: int = ROUND_TO):
        self.session, self.past_names, self.present_names = session, past_names, present_names
        self.kv_shape, self.ort_value, self.run_options = kv_shape, ort_value, run_options
        self.chunk, self.one_layer, self.round_to = chunk, one_layer, round_to
        self.rows = 0
        self.kv: np.ndarray | None = None  # (layers x {key, value}, batch 1, kv heads, rows, head dim)
        self._values: list = []  # one OrtValue per past input, views of ``kv``
        self.io = self.io_single = None
        self.lock = threading.Lock()

    def reserve(self, needed: int) -> None:
        rows = capacity(needed, self.rows, self.round_to)
        if rows == self.rows:
            return
        self.io = self.io_single = self.kv = None  # the old buffer goes before the new one is made
        self._values = []
        with _without_huge_pages():
            self.kv = np.empty((len(self.past_names), 1, self.kv_shape[0], rows, self.kv_shape[1]), np.float32)
        self.rows = rows
        self._values = [self.ort_value(self.kv[i]) for i in range(len(self.past_names))]
        self.io = self._binding(self._values)
        # every layer's keys on the first layer's key rows, every layer's values on the first layer's value rows
        first: dict[str, Any] = {}
        for name, value in zip(self.past_names, self._values):
            first.setdefault(name.rsplit(".", 1)[1], value)
        self.io_single = self._binding([first[name.rsplit(".", 1)[1]] for name in self.past_names])

    def _binding(self, values: list):
        io = self.session.io_binding()
        io.bind_output("logits", "cpu")  # first, so it stays output 0 when each pass rebinds it
        for past, present, value in zip(self.past_names, self.present_names, values):
            io.bind_ortvalue_input(past, value)
            io.bind_ortvalue_output(present, value)
        return io

    def extend(self, ids: list[int], start: int, io=None, chunk: int | None = None) -> np.ndarray:
        """Append ``ids`` after ``start`` cached rows; the label logits at the last position."""
        io = io or self.io
        for a, b, total in steps(len(ids), start, self.chunk if chunk is None else chunk):
            io.bind_cpu_input("input_ids", np.array([ids[a:b]], np.int64))
            io.bind_cpu_input("attention_mask", np.ones((1, total), np.int64))
            io.bind_output("logits", "cpu")
            self.session.run_with_iobinding(io, self.run_options)
        return io.get_outputs()[0].numpy()[0, -1].copy()

    def run(self, prefix: list[int], suffixes: Sequence[list[int]]) -> list[np.ndarray]:
        """Label logits at the end of ``prefix + suffix``, for each suffix."""
        if not suffixes:
            return []
        with self.lock:
            self.reserve(len(prefix) + max(map(len, suffixes)))
            if len(suffixes) == 1:  # one pass, nothing read back: each layer's KV may overwrite the previous one's
                if self.one_layer:
                    return [self.extend(prefix + suffixes[0], 0, self.io_single, 0)]
                return [self.extend(prefix + suffixes[0], 0)]
            self.extend(prefix, 0)
            return [self.extend(s, len(prefix)) for s in suffixes]


class Decider(_Reference):
    def __init__(self, path: str, threads: int | None = None, low_memory: bool = True):
        import onnxruntime as ort

        local = Path(path)
        if not local.exists():  # a Hub repo: fetch only its onnx/ folder, not the safetensors weights
            from huggingface_hub import snapshot_download

            # as real files, not the Hub cache's symlinks: onnxruntime (1.30+) refuses external weights whose
            # resolved path leaves the model's folder, which a symlink into the cache's blob store does
            home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
            local = Path(snapshot_download(path, allow_patterns=["onnx/*"], local_dir=home / "arc-decide" / path))
            local = local / "onnx"
        self.meta = json.loads((local / "arcd_serving.json").read_text())
        if self.meta.get("prompt_hash") != PROMPT_HASH:
            raise ValueError("this client's prompt does not match the checkpoint's")
        self.tokenizer = _Tokenizer(local / "tokenizer.json")
        self.max_state_tokens = self.meta.get("max_state_tokens") or 1400

        so = ort.SessionOptions()
        so.intra_op_num_threads = threads or cpu_budget()
        if low_memory:
            exact_arena(ort)
            so.add_session_config_entry("session.use_env_allocators", "1")
        self.session = ort.InferenceSession(str(local / "model.onnx"), so, providers=["CPUExecutionProvider"])
        labels = json.loads(self.session.get_modelmeta().custom_metadata_map["arcd_label_tokens"])
        self.column = {t: i for i, t in enumerate(labels)}
        self.past_names = [i.name for i in self.session.get_inputs() if i.name.startswith("past_key_values.")]
        self.present_names = [n.replace("past_key_values", "present") for n in self.past_names]
        cfg = json.loads((local / "config.json").read_text())
        self._kv_shape = (cfg["num_key_value_heads"],
                          cfg.get("head_dim") or cfg["hidden_size"] // cfg["num_attention_heads"])
        self.kv: SharedKV | None = None
        if low_memory:
            shrink = ort.RunOptions()
            shrink.add_run_config_entry("memory.enable_memory_arena_shrinkage", "cpu:0")
            self.kv = SharedKV(self.session, self.past_names, self.present_names, self._kv_shape,
                               ort.OrtValue.ortvalue_from_numpy, shrink)

    def _empty_past(self) -> dict[str, np.ndarray]:
        return dict.fromkeys(self.past_names, np.zeros((1, self._kv_shape[0], 0, self._kv_shape[1]), np.float32))

    def _run(self, ids: np.ndarray, mask: np.ndarray, past: dict, cache: bool) -> list[np.ndarray]:
        names = ["logits", *self.present_names] if cache else ["logits"]
        return self.session.run(names, {"input_ids": ids, "attention_mask": mask, **past})

    def _probs(self, logits: np.ndarray, name: str, q: dict) -> tuple[str, list[float]]:
        kind, tokens, bias = self._head(name, q)
        t = self._temperature(kind, name)
        return kind, _softmax([(float(logits[self.column[i]]) + b) / t for i, b in zip(tokens, bias)])

    def decide(self, state: Any, questions: dict[str, dict]) -> dict[str, dict]:
        """Every question about one state; the state is encoded once and reused through the KV cache."""
        enc = self.tokenizer.encode
        prefix = enc(prefix_text(self.state_text(state)))
        if self.kv is not None:
            logits = self.kv.run(prefix, [enc(suffix_text(q)) for q in questions.values()])
            out = {}
            for (name, q), z in zip(questions.items(), logits):
                kind, p = self._probs(z, name, q)
                out[name] = self._answer(q, kind, p)
            return out
        if len(questions) == 1:
            (name, q), = questions.items()
            ids = prefix + enc(suffix_text(q))
            logits = self._run(np.array([ids], np.int64), np.ones((1, len(ids)), np.int64), self._empty_past(), False)[0]
            kind, p = self._probs(logits[0, -1], name, q)
            return {name: self._answer(q, kind, p)}
        first = self._run(np.array([prefix], np.int64), np.ones((1, len(prefix)), np.int64), self._empty_past(), True)
        past = dict(zip(self.past_names, first[1:]))  # inputs are never written to, so no copy per question
        out = {}
        for name, q in questions.items():
            suffix = enc(suffix_text(q))
            mask = np.ones((1, len(prefix) + len(suffix)), np.int64)
            logits = self._run(np.array([suffix], np.int64), mask, past, False)[0]
            kind, p = self._probs(logits[0, -1], name, q)
            out[name] = self._answer(q, kind, p)
        return out
