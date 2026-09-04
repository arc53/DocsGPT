import pytest


@pytest.fixture(scope="session")
def _mpnet_tokenizer():
    """Real WordPiece tokenizer; skipped when the hub is unreachable."""
    pytest.importorskip("tokenizers")
    from tokenizers import Tokenizer

    try:
        tokenizer = Tokenizer.from_pretrained("sentence-transformers/all-mpnet-base-v2")
    except Exception as exc:  # offline CI
        pytest.skip(f"tokenizer unavailable: {exc}")
    tokenizer.no_padding()
    tokenizer.no_truncation()
    return tokenizer


@pytest.fixture
def hf_counter(_mpnet_tokenizer):
    from application.parser.tokenization import HuggingFaceCounter

    return HuggingFaceCounter(_mpnet_tokenizer, "sentence-transformers/all-mpnet-base-v2")
