"""OCR rate limits: the 429 time budget, rate-limit headers, the shared in-flight limit,
pages kept across a retry, and files deferred by the directory reader.

The HTTP layer, the clock and the sleeps are faked throughout.
"""
import threading
import time
from email.utils import formatdate
from pathlib import Path

import pytest

pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")

from docsgpt.parser.file import bulk  # noqa: E402
from docsgpt.parser.file import ocr_limiter  # noqa: E402
from docsgpt.parser.file import ocr_parser as op  # noqa: E402
from docsgpt.parser.file.base_parser import BaseParser, DocumentParseError, TransientParseError  # noqa: E402
from tests.parser.file.test_deepseek_ocr_api import (  # noqa: E402
    FakePost,
    FakeResponse,
    _image,
    _image_pdf,
    settings,  # noqa: F401 - fixture
    sleeps,  # noqa: F401 - fixture
)
from tests.parser.file.test_ocr_limiter import FakeRedis  # noqa: E402


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock that only moves when the engine sleeps."""
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(op, "_monotonic", lambda: now[0])
    monkeypatch.setattr(op, "_sleep", sleep)
    return now


@pytest.fixture
def budget(settings, monkeypatch):  # noqa: F811
    # Through monkeypatch, so these (and later assignments in a test) are put back.
    monkeypatch.setattr(settings, "OCR_RATE_LIMIT_MAX_WAIT", 300.0)
    monkeypatch.setattr(settings, "OCR_MAX_IN_FLIGHT", 8)
    monkeypatch.setattr(settings, "OCR_RATE_LIMIT_COOLDOWN", settings.OCR_RATE_LIMIT_COOLDOWN)
    # A developer's own Redis must not decide these tests' limits; one that wants Redis installs FakeRedis.
    monkeypatch.setattr(ocr_limiter, "_redis_client", lambda: None)
    return settings


@pytest.mark.unit
class TestRateLimitHeaders:
    def test_retry_after_ms_sets_the_wait(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429, headers={"retry-after-ms": "2500"})))
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 0.5)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert sleeps == [2.5]

    def test_retry_after_seconds_is_read_whatever_its_case(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429, headers={"retry-after": "2"})))
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 0.5)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert sleeps == [2.0]

    def test_retry_after_http_date_sets_the_wait(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr(op, "_wall_now", lambda: 1_700_000_000.0)
        when = formatdate(1_700_000_000.0 + 12, usegmt=True)
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429, headers={"Retry-After": when})))
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 0.5)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert sleeps == [12.0]

    def test_backoff_wins_over_a_shorter_header(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429, headers={"Retry-After": "1"})))
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 4.0)
        op.DeepseekOcrEngine().ocr_image(_image())
        assert sleeps == [4.0]


@pytest.mark.unit
class TestRateLimitBudget:
    def test_429_retries_until_the_budget_runs_out(self, budget, monkeypatch, clock):
        budget.OCR_DEEPSEEK_MAX_RETRIES = 1  # does not limit 429 retries
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 0.5)
        post = FakePost(*(FakeResponse(status=429, headers={"Retry-After": "30"}) for _ in range(100)))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrRateLimitedError) as caught:
            op.DeepseekOcrEngine().ocr_image(_image())
        assert isinstance(caught.value, TransientParseError)
        # 30 s apart while the next answer can still come inside 300 s: the
        # wait that would end at the budget is not taken, nothing is sent past it.
        assert len(post.calls) == 10
        assert clock[0] == pytest.approx(270.0)

    def test_a_wait_longer_than_the_budget_left_defers_at_once(self, budget, monkeypatch, clock):
        budget.OCR_RATE_LIMIT_MAX_WAIT = 50
        post = FakePost(FakeResponse(status=429, headers={"Retry-After": "55"}), FakeResponse())
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrRateLimitedError):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1
        assert clock[0] == pytest.approx(0.0)

    def test_429_succeeds_inside_the_budget(self, budget, monkeypatch, clock):
        post = FakePost(*(FakeResponse(status=429, headers={"Retry-After": "40"}) for _ in range(5)), FakeResponse())
        monkeypatch.setattr("requests.post", post)
        assert op.DeepseekOcrEngine().ocr_image(_image()) == "OCR TEXT"
        assert len(post.calls) == 6

    def test_zero_budget_does_not_retry(self, budget, monkeypatch, clock):
        budget.OCR_RATE_LIMIT_MAX_WAIT = 0
        post = FakePost(FakeResponse(status=429), FakeResponse())
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(op.OcrRateLimitedError):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 1

    def test_server_errors_stop_at_max_retries_as_transient(self, budget, monkeypatch, clock):
        budget.OCR_DEEPSEEK_MAX_RETRIES = 2
        post = FakePost(*(FakeResponse(status=502) for _ in range(10)))
        monkeypatch.setattr("requests.post", post)
        with pytest.raises(TransientParseError, match="502"):
            op.DeepseekOcrEngine().ocr_image(_image())
        assert len(post.calls) == 3

    def test_refused_connection_and_read_timeout_are_transient(self, budget, monkeypatch, sleeps):  # noqa: F811
        import requests

        budget.OCR_DEEPSEEK_MAX_RETRIES = 0
        monkeypatch.setattr("requests.post", FakePost(requests.ConnectionError("refused")))
        with pytest.raises(TransientParseError):
            op.DeepseekOcrEngine().ocr_image(_image())
        monkeypatch.setattr("requests.post", FakePost(requests.ReadTimeout("slow")))
        with pytest.raises(TransientParseError, match="OCR_DEEPSEEK_TIMEOUT"):
            op.DeepseekOcrEngine().ocr_image(_image())

    def test_rejected_key_stays_permanent(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=401)))
        with pytest.raises(op.OcrUnavailableError) as caught:
            op.DeepseekOcrEngine().ocr_image(_image())
        assert not isinstance(caught.value, TransientParseError)

    def test_429_halves_the_shared_limit(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429)))
        engine = op.DeepseekOcrEngine()
        engine.ocr_image(_image())
        assert engine.limiter.allowed() == 4

    def test_rate_limit_stats_are_counted_and_reset(self, budget, monkeypatch, sleeps):  # noqa: F811
        monkeypatch.setattr(op, "_backoff_seconds", lambda attempt: 1.5)
        monkeypatch.setattr("requests.post", FakePost(FakeResponse(status=429), FakeResponse(status=429)))
        engine = op.DeepseekOcrEngine()
        engine.ocr_image(_image())
        assert engine.rate_limit_stats() == {"attempts": 3, "rate_limited": 2, "waited_seconds": 3.0}
        engine.reset_usage()
        assert engine.rate_limit_stats() == {"attempts": 0, "rate_limited": 0, "waited_seconds": 0.0}


class SlowPost:
    """``requests.post`` that takes a while and records how many calls overlap."""

    def __init__(self):
        self.in_flight = 0
        self.peak = 0
        self.calls = 0
        self.lock = threading.Lock()

    def __call__(self, url, json=None, headers=None, timeout=None):
        with self.lock:
            self.calls += 1
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        time.sleep(0.005)
        with self.lock:
            self.in_flight -= 1
        return FakeResponse()


@pytest.mark.unit
class TestSharedInFlightLimit:
    def test_two_engines_sharing_redis_never_exceed_the_cap(self, budget, monkeypatch):
        redis = FakeRedis()
        monkeypatch.setattr(ocr_limiter, "_redis_client", lambda: redis)
        monkeypatch.setattr(ocr_limiter, "_sleep", lambda seconds: time.sleep(0.001))
        budget.OCR_MAX_IN_FLIGHT = 3
        budget.OCR_DEEPSEEK_CONCURRENCY = 4
        post = SlowPost()
        monkeypatch.setattr("requests.post", post)
        first = op.DeepseekOcrEngine()
        second = op.DeepseekOcrEngine()
        # Two worker processes: their own limiter objects, one Redis.
        second.limiter = ocr_limiter.InFlightLimiter(first.limiter.key, 3, 60)

        def run(engine):
            op.ocr_images(engine, ((index, _image()) for index in range(12)))

        threads = [threading.Thread(target=run, args=(engine,)) for engine in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert post.calls == 24
        assert 1 < post.peak <= 3

    def test_without_redis_the_process_limit_applies(self, budget, monkeypatch):
        budget.OCR_MAX_IN_FLIGHT = 2
        budget.OCR_DEEPSEEK_CONCURRENCY = 4
        post = SlowPost()
        monkeypatch.setattr("requests.post", post)
        engines = [op.DeepseekOcrEngine(), op.DeepseekOcrEngine()]
        assert engines[0].limiter is engines[1].limiter

        threads = [
            threading.Thread(target=op.ocr_images, args=(engine, ((i, _image()) for i in range(8))))
            for engine in engines
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert post.calls == 16
        assert post.peak <= 2


# ---------------------------------------------------------------------------
# Pages kept across a retry
# ---------------------------------------------------------------------------


class ScriptedEngine:
    """Answers pages by index; ``fail`` maps a page to the error its next request raises."""

    name = "scripted"
    concurrency = 1

    def __init__(self, fail=None):
        self.fail = dict(fail or {})
        self.sent = []

    def ocr_image(self, image):
        index = image.info["page"]
        self.sent.append(index)
        error = self.fail.pop(index, None)
        if error is not None:
            raise error
        return f"page {index} recognised words"


@pytest.mark.unit
class TestPagesKeptAcrossRetry:
    def test_one_failed_page_keeps_the_others_and_only_it_is_sent_again(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=3)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1, 2}))
        engine = ScriptedEngine(fail={1: TransientParseError("502 from the endpoint")})
        parser = op.NativeOcrPdfParser(engine=engine)

        with pytest.raises(TransientParseError, match="502"):
            parser.parse_file(pdf)
        assert sorted(engine.sent) == [0, 1, 2]

        engine.sent.clear()
        # The retry renders only the missing page.
        monkeypatch.setattr(op, "_render_page", _tagging_render({1}))
        content = parser.parse_file(pdf)

        assert engine.sent == [1]
        assert content == "\n\n".join(f"page {i} recognised words" for i in range(3))
        assert parser.get_file_metadata(pdf)["ocr_pages"] == 3

    def test_a_rate_limit_stops_sending_and_the_retry_sends_the_rest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=3)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1, 2}))
        engine = ScriptedEngine(fail={1: op.OcrRateLimitedError("rate limited")})
        parser = op.NativeOcrPdfParser(engine=engine)

        with pytest.raises(op.OcrRateLimitedError, match="2 of 3 scanned page"):
            parser.parse_file(pdf)
        assert engine.sent == [0, 1]  # page 2 would only have been rate limited too

        engine.sent.clear()
        monkeypatch.setattr(op, "_render_page", _tagging_render({1, 2}))
        content = parser.parse_file(pdf)
        assert engine.sent == [1, 2]
        assert content == "\n\n".join(f"page {i} recognised words" for i in range(3))

    def test_an_edited_file_is_not_answered_from_kept_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=2)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1}))
        engine = ScriptedEngine(fail={1: op.OcrRateLimitedError("rate limited")})
        parser = op.NativeOcrPdfParser(engine=engine)
        with pytest.raises(op.OcrRateLimitedError):
            parser.parse_file(pdf)

        _image_pdf(tmp_path / "other.pdf", pages=3)
        pdf.write_bytes(_first_pages(tmp_path / "other.pdf", 2))  # new bytes at the same path
        engine.sent.clear()
        monkeypatch.setattr(op, "_render_page", _tagging_render({1, 2}))
        parser.parse_file(pdf)
        # Both pages of the new content are sent; nothing of the old file is reused.
        assert sorted(engine.sent) == [1, 2]

    def test_a_permanent_page_failure_raises_that_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=2)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1}))
        parser = op.NativeOcrPdfParser(engine=ScriptedEngine(fail={0: DocumentParseError("bad page")}))
        with pytest.raises(DocumentParseError, match="bad page"):
            parser.parse_file(pdf)

    def test_ocr_pages_records_skipped_pages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=3)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1, 2}))
        parser = op.NativeOcrPdfParser(engine=ScriptedEngine(fail={2: DocumentParseError("bad page")}))
        texts = parser.ocr_pages(pdf, [0, 1, 2], skip_failed=True)
        assert sorted(texts) == [0, 1]
        assert parser.last_ocr_failed_pages == 1

    def test_ocr_pages_raises_a_rate_limit_after_keeping_the_rest(self, tmp_path, monkeypatch):
        monkeypatch.setattr(op, "render_dpi", lambda: 72)
        pdf = _image_pdf(tmp_path / "scan.pdf", pages=3)
        monkeypatch.setattr(op, "_render_page", _tagging_render({0, 1, 2}))
        engine = ScriptedEngine(fail={1: op.OcrRateLimitedError("rate limited")})
        parser = op.NativeOcrPdfParser(engine=engine)
        with pytest.raises(op.OcrRateLimitedError):
            parser.ocr_pages(pdf, [0, 1, 2], skip_failed=True)

        assert engine.sent == [0, 1]

        engine.sent.clear()
        monkeypatch.setattr(op, "_render_page", _tagging_render({1, 2}))
        texts = parser.ocr_pages(pdf, [0, 1, 2], skip_failed=True)
        assert engine.sent == [1, 2]
        assert sorted(texts) == [0, 1, 2]
        assert parser.last_ocr_failed_pages == 0


def _page_of(image) -> int:
    """Which ``_image_pdf`` page an image shows: page ``i`` has a ``3 + i`` pixel border around 200 x 300 points."""
    gray = image.convert("L")
    dark = sum(1 for value in gray.getdata() if value < 128)
    scale = (gray.width / 300) ** 2
    return round(dark / (1000 * scale)) - 3


def _tagging_render(indices):
    """A ``_render_page`` stand-in that tags each image with the page it actually shows.

    ``indices`` are the pages the test expects to be rendered; a page outside
    them fails the test.
    """
    expected = set(indices)
    original = _real_render

    def render(page, dpi):
        image = original(page, dpi)
        index = _page_of(image)
        assert index in expected, f"rendered page {index}, expected one of {sorted(expected)}"
        image.info["page"] = index
        return image

    return render


_real_render = op._render_page


def _first_pages(path: Path, count: int) -> bytes:  # noqa: D401
    """The bytes of a PDF holding the last ``count`` pages of ``path``, so its content differs from page 0's."""
    import io

    import pypdfium2 as pdfium

    source = pdfium.PdfDocument(str(path))
    out = pdfium.PdfDocument.new()
    out.import_pages(source, list(range(len(source) - count, len(source))))
    buffer = io.BytesIO()
    out.save(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# AnydocParser surfaces skipped pages
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAnydocSkippedPages:
    def _parser(self, monkeypatch, texts, raises=None):
        from docsgpt.parser.file import anydoc_parser as ap

        class Fallback(BaseParser):
            ocr_enabled = True
            batch_ocr_pages = True
            last_ocr_usage = {}

            def _init_parser(self):
                return {}

            def parse_file(self, file, errors="ignore"):
                return ""

            def ocr_pages(self, path, indices, skip_failed=False):
                if raises is not None:
                    raise raises
                return dict(texts)

        monkeypatch.setattr(op, "scanned_page_indices", lambda path: [1, 2])
        parser = ap.AnydocParser(fallback_parser=Fallback())
        return parser

    def test_pages_left_out_are_counted(self, monkeypatch, tmp_path):
        parser = self._parser(monkeypatch, {1: "page two words"})
        path = tmp_path / "mixed.pdf"
        content = parser._ocr_scanned_pages(path, "text page")
        assert "page two words" in content
        assert parser.get_file_metadata(path)["ocr_pages_failed"] == 1

    def test_a_failed_ocr_call_counts_every_page(self, monkeypatch, tmp_path):
        parser = self._parser(monkeypatch, {}, raises=DocumentParseError("boom"))
        path = tmp_path / "mixed.pdf"
        assert parser._ocr_scanned_pages(path, "text page") == "text page"
        assert parser.get_file_metadata(path)["ocr_pages_failed"] == 2

    def test_a_rate_limit_is_raised_so_the_file_is_deferred(self, monkeypatch, tmp_path):
        parser = self._parser(monkeypatch, {}, raises=op.OcrRateLimitedError("later"))
        with pytest.raises(op.OcrRateLimitedError):
            parser._ocr_scanned_pages(tmp_path / "mixed.pdf", "text page")

    def test_nothing_left_out_sets_no_key(self, monkeypatch, tmp_path):
        parser = self._parser(monkeypatch, {1: "two", 2: "three"})
        path = tmp_path / "mixed.pdf"
        parser._ocr_scanned_pages(path, "text page")
        assert "ocr_pages_failed" not in parser.get_file_metadata(path)


# ---------------------------------------------------------------------------
# SimpleDirectoryReader defers rate-limited files
# ---------------------------------------------------------------------------


class FlakyParser(BaseParser):
    """Raises the scripted error for a file on its first parses, then reads it."""

    def __init__(self, errors_by_name):
        super().__init__()
        self.errors_by_name = {name: list(errs) for name, errs in errors_by_name.items()}
        self.parsed = []

    def _init_parser(self):
        return {}

    def parse_file(self, file, errors="ignore"):
        self.parsed.append(Path(file).name)
        queued = self.errors_by_name.get(Path(file).name)
        if queued:
            raise queued.pop(0)
        return f"text of {Path(file).name}"


@pytest.fixture
def reader_sleeps(monkeypatch, settings):  # noqa: F811
    monkeypatch.setattr(settings, "OCR_RATE_LIMIT_COOLDOWN", 45.0)
    recorded = []
    monkeypatch.setattr(bulk, "_sleep", recorded.append)
    return recorded


def _files(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text("x")
    return tmp_path


@pytest.mark.unit
class TestDeferredFiles:
    def test_a_rate_limited_file_succeeds_on_the_deferred_pass(self, tmp_path, reader_sleeps):
        parser = FlakyParser({"b.scan": [op.OcrRateLimitedError("busy")]})
        reader = bulk.SimpleDirectoryReader(
            input_dir=str(_files(tmp_path, "a.scan", "b.scan", "c.scan")),
            file_extractor={".scan": parser},
            file_metadata=lambda name: {},
        )
        progress = []
        docs = reader.load_data(progress_callback=lambda done, total: progress.append((done, total)))

        assert sorted(d.text for d in docs) == ["text of a.scan", "text of b.scan", "text of c.scan"]
        assert reader.failed_files == []
        assert reader.transient_failures == set()
        assert parser.parsed == ["a.scan", "b.scan", "c.scan", "b.scan"]
        assert reader_sleeps == [45.0]
        assert progress[-1] == (3, 3)

    def test_still_rate_limited_after_the_pass_is_a_transient_failure(self, tmp_path, reader_sleeps):
        limited = [op.OcrRateLimitedError("busy"), op.OcrRateLimitedError("still busy")]
        parser = FlakyParser({"b.scan": limited, "c.scan": [DocumentParseError("corrupt")]})
        reader = bulk.SimpleDirectoryReader(
            input_dir=str(_files(tmp_path, "a.scan", "b.scan", "c.scan")),
            file_extractor={".scan": parser},
        )
        reader.load_data()

        failed = {path.name: message for path, message in reader.failed_files}
        assert failed == {"b.scan": "still busy", "c.scan": "corrupt"}
        assert {path.name for path in reader.transient_failures} == {"b.scan"}

    def test_other_transient_errors_are_listed_without_a_deferred_pass(self, tmp_path, reader_sleeps):
        parser = FlakyParser({"a.scan": [TransientParseError("502")]})
        reader = bulk.SimpleDirectoryReader(
            input_dir=str(_files(tmp_path, "a.scan", "b.scan")),
            file_extractor={".scan": parser},
        )
        reader.load_data()
        assert {path.name for path in reader.transient_failures} == {"a.scan"}
        assert reader_sleeps == []

    def test_no_cool_down_without_deferred_files(self, tmp_path, reader_sleeps):
        reader = bulk.SimpleDirectoryReader(
            input_dir=str(_files(tmp_path, "a.scan")),
            file_extractor={".scan": FlakyParser({})},
        )
        reader.load_data()
        assert reader_sleeps == []

    def test_transient_failures_reset_per_load(self, tmp_path, reader_sleeps):
        parser = FlakyParser({"a.scan": [TransientParseError("502")]})
        reader = bulk.SimpleDirectoryReader(
            input_dir=str(_files(tmp_path, "a.scan", "b.scan")),
            file_extractor={".scan": parser},
        )
        reader.load_data()
        reader.load_data()
        assert reader.transient_failures == set()


class TestMixedPageFailures:
    def test_skipping_failed_pages_still_defers_a_rate_limited_file(self, tmp_path):
        from PIL import Image

        from docsgpt.parser.file.base_parser import DocumentParseError

        pages = [Image.new("RGB", (200, 200), "white") for _ in range(2)]
        pdf = tmp_path / "mixed.pdf"
        pages[0].save(pdf, save_all=True, append_images=pages[1:])
        outcomes = [DocumentParseError("the model refused this page"), op.OcrRateLimitedError("429")]

        class Engine:
            name = "fake"
            concurrency = 1

            def ocr_image(self, image):
                raise outcomes.pop(0)

        parser = op.NativeOcrPdfParser(engine=Engine())
        with pytest.raises(op.OcrRateLimitedError):
            parser.ocr_pages(pdf, [0, 1], skip_failed=True)


class TestSlotWaitDeadline:
    def test_a_retry_stops_waiting_for_a_slot_when_the_budget_runs_out(self, budget, monkeypatch, clock):
        engine = op.DeepseekOcrEngine()

        class Full:
            def _acquire(self, give_up=None):
                while not give_up():
                    clock[0] += 10  # time passes while every slot stays held
                raise ocr_limiter.SlotWaitExpired("gave up")

        import contextlib

        @contextlib.contextmanager
        def slot(give_up=None):
            Full()._acquire(give_up)
            yield

        monkeypatch.setattr(engine.limiter, "slot", slot)
        with pytest.raises(op.OcrRateLimitedError):
            engine._send({}, {}, deadline=op._monotonic() + 30)


class TestSlotWaitDeadlineWithRedis:
    def test_a_retry_gives_up_while_another_request_holds_the_only_slot(self, budget, monkeypatch):
        from tests.parser.file.test_ocr_limiter import FakeRedis

        redis = FakeRedis()
        monkeypatch.setattr(ocr_limiter, "_redis_client", lambda: redis)
        monkeypatch.setattr(ocr_limiter, "_sleep", lambda seconds: None)
        monkeypatch.setattr(budget, "OCR_MAX_IN_FLIGHT", 1)
        ocr_limiter.reset_limiters()
        engine = op.DeepseekOcrEngine()
        clock = {"now": 0.0}

        def tick():
            clock["now"] += 1.0
            return clock["now"]

        monkeypatch.setattr(op, "_monotonic", tick)
        with engine.limiter.slot():  # every slot taken
            with pytest.raises(op.OcrRateLimitedError, match="waiting for a request slot"):
                engine._send({}, {}, deadline=5.0)
