"""The decision model on PyTorch, for ``docsgpt decide-server --device mps|cuda`` only.

A Mac's GPU is reachable only from a native process (Docker on a Mac has no Metal), and torch cannot share a macOS
process with faiss, DocsGPT's default vector store: both bring their own OpenMP runtime, and loading the two aborts
the process. So this backend runs in the decide-server alone, never in the API or a worker, and torch comes from
the ``decisions-torch`` extra, which no image installs.

It is the ONNX backend's lifecycle (load thread, memory guard, timing run, gate, lanes, drift) over the vendored
release PyTorch client, which keeps the label rows of the output head and runs the decoder alone. The release
client's call is split into its passes so the gate can be released between them: the state's prompt is one pass,
and every question extends that pass's KV cache and is cut back off it (``cache.crop``), as the release client does.
A hot call therefore waits for at most one background pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from docsgpt.decisions import files
from docsgpt.decisions.backends.onnx import OnnxBackend
from docsgpt.decisions.questions import family
from docsgpt.decisions.vendor.arc_decide import Decider as ReleaseDecider
from docsgpt.decisions.vendor.arc_decide import _softmax

#: Weight type per device: fp16 on Apple GPUs, as the release measured them; bf16 on NVIDIA.
DTYPES = {"mps": "float16", "cuda": "bfloat16"}
_SHORT = {"float16": "fp16", "bfloat16": "bf16"}


class _Tokens:
    """The transformers tokenizer with the release client's ``add_special_tokens=False`` as the default."""

    def __init__(self, tokenizer: Any):
        self._tokenizer = tokenizer

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return self._tokenizer.encode(text, add_special_tokens=add_special_tokens)

    def decode(self, ids: list[int]) -> str:
        return self._tokenizer.decode(ids)


class TorchKV:
    """One lane's KV cache, with the interface the ONNX backend drives (``SharedKV``'s ``reserve`` and ``extend``)."""

    io = io_single = None  # the torch plan has no single pass and no I/O binding

    def __init__(self, engine: "TorchEngine"):
        self.engine = engine
        self.cache: Any = None
        self.rows = 0

    def reserve(self, needed: int) -> None:
        """Nothing to do: the cache grows as passes append to it."""

    def extend(self, ids: list[int], start: int, io: Any, chunk: int) -> Any:
        """Append ``ids`` after the first ``start`` cached rows; the label logits at the last position.

        A pass from row 0 starts a new cache (a new state); a question's pass first cuts off the previous
        question's rows, leaving the state's. The cut passes ``crop`` the negative count of rows to remove, the
        only form transformers accepts from 5.20 on (a positive value, read as the length to keep up to 5.19,
        raises there), and is skipped when there is nothing to remove.

        Args:
            ids: The token ids of this pass.
            start: How many cached rows the pass follows: 0 for a state, the state's length for a question.
            io: Unused; the ONNX backend's I/O binding.
            chunk: Unused; the ONNX backend's chunk size.

        Returns:
            The label logits at the pass's last position, on the CPU.
        """
        import torch

        engine = self.engine
        with torch.inference_mode():
            if start == 0:
                self.cache = None
            elif self.rows > start:
                self.cache.crop(start - self.rows)
            out = engine.decoder(torch.tensor([ids], device=engine.device), past_key_values=self.cache, use_cache=True)
            self.cache, self.rows = out.past_key_values, start + len(ids)
            # to the CPU: the copy waits for the GPU, so the pass is timed whole
            return (engine.head @ out.last_hidden_state[0, -1]).float().cpu()


class TorchEngine(ReleaseDecider):
    """The release PyTorch client with family temperatures, and a KV cache per lane."""

    def __init__(self, path: str, device: str):
        super().__init__(path, device=device, dtype=DTYPES[device])
        self.tokenizer = _Tokens(self.tokenizer)
        self.threads = 0  # GPU work; the profile's thread count is the CPU runtime's
        self.kv = self.new_buffer()

    def _temperature(self, kind: str, name: str) -> float:
        return super()._temperature(kind, family(name))

    def new_buffer(self) -> TorchKV:
        """An empty KV cache for a lane."""
        return TorchKV(self)

    def answer(self, logits: Any, key: str, question: dict) -> dict:
        """The wire-shaped answer to one question from its label logits, as the release client computes it."""
        kind, tokens, bias = self._head(key, question)
        t = self._temperature(kind, key)
        p = _softmax([(logits[self.column[i]].item() + b) / t for i, b in zip(tokens, bias)])
        return self._answer(question, kind, p)


class TorchBackend(OnnxBackend):
    """The decision model on a GPU through PyTorch, loaded on first use; see the module docstring."""

    PLAN = "torch"

    def __init__(self, spec, device: str, **kwargs: Any):
        """Create an idle backend; nothing is read, loaded or imported.

        Args:
            spec: The model to load.
            device: ``mps`` or ``cuda``.
            **kwargs: ``open_engine`` and ``clock``, as ``OnnxBackend`` takes them.
        """
        if device not in DTYPES:
            raise ValueError(f"the torch runtime runs on {' or '.join(DTYPES)}, not {device!r}")
        super().__init__(spec, **kwargs)
        self.device = device

    @property
    def runtime(self) -> str:
        return f"torch-{self.device}-{_SHORT[DTYPES[self.device]]}"

    def _files(self) -> Path:
        return files.ensure_torch(self.spec)

    def _build_engine(self, folder: Path) -> TorchEngine:
        from docsgpt.core.optional_deps import require

        require("torch", "the decide-server's torch runtime")
        require("transformers", "the decide-server's torch runtime")
        return TorchEngine(str(folder), self.device)

    def _schedule_tick(self) -> None:
        """No CPU-budget checks: the passes run on the GPU."""
