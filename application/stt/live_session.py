import json
import re
import uuid
from typing import Dict, Optional


LIVE_STT_SESSION_PREFIX = "stt_live_session:"
LIVE_STT_SESSION_TTL_SECONDS = 15 * 60
LIVE_STT_MUTABLE_TAIL_WORDS = 8
LIVE_STT_SILENCE_MUTABLE_TAIL_WORDS = 2
LIVE_STT_MIN_COMMITTED_OVERLAP_WORDS = 2


def normalize_transcript_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def join_transcript_parts(*parts: str) -> str:
    return " ".join(part for part in map(normalize_transcript_text, parts) if part)


def _normalize_word(word: str) -> str:
    normalized = re.sub(r"[^\w]+", "", word.casefold(), flags=re.UNICODE)
    return normalized or word.casefold()


def _split_words(text: str) -> list[str]:
    normalized = normalize_transcript_text(text)
    return normalized.split() if normalized else []


def _common_prefix_length(left_words: list[str], right_words: list[str]) -> int:
    max_index = min(len(left_words), len(right_words))
    prefix_length = 0
    for index in range(max_index):
        if _normalize_word(left_words[index]) != _normalize_word(right_words[index]):
            break
        prefix_length += 1
    return prefix_length


def _find_suffix_prefix_overlap(
    left_words: list[str], right_words: list[str], min_overlap: int
) -> int:
    max_overlap = min(len(left_words), len(right_words))
    if max_overlap < min_overlap:
        return 0

    left_keys = [_normalize_word(word) for word in left_words]
    right_keys = [_normalize_word(word) for word in right_words]

    for overlap_size in range(max_overlap, min_overlap - 1, -1):
        if left_keys[-overlap_size:] == right_keys[:overlap_size]:
            return overlap_size
    return 0


def strip_committed_prefix(committed_text: str, hypothesis_text: str) -> str:
    committed_words = _split_words(committed_text)
    hypothesis_words = _split_words(hypothesis_text)
    if not committed_words or not hypothesis_words:
        return normalize_transcript_text(hypothesis_text)

    full_prefix_length = _common_prefix_length(committed_words, hypothesis_words)
    if full_prefix_length == len(committed_words):
        return " ".join(hypothesis_words[full_prefix_length:])

    overlap_size = _find_suffix_prefix_overlap(
        committed_words,
        hypothesis_words,
        LIVE_STT_MIN_COMMITTED_OVERLAP_WORDS,
    )
    if overlap_size:
        return " ".join(hypothesis_words[overlap_size:])
    return " ".join(hypothesis_words)


def _calculate_commit_count(
    previous_hypothesis: str, current_hypothesis: str, is_silence: bool
) -> int:
    previous_words = _split_words(previous_hypothesis)
    current_words = _split_words(current_hypothesis)
    if not current_words:
        return 0

    if not previous_words:
        if is_silence:
            return max(0, len(current_words) - LIVE_STT_SILENCE_MUTABLE_TAIL_WORDS)
        return 0

    stable_prefix_length = _common_prefix_length(previous_words, current_words)
    if not stable_prefix_length:
        return 0

    mutable_tail_words = (
        LIVE_STT_SILENCE_MUTABLE_TAIL_WORDS
        if is_silence
        else LIVE_STT_MUTABLE_TAIL_WORDS
    )
    max_committable_by_tail = max(0, len(current_words) - mutable_tail_words)
    return min(stable_prefix_length, max_committable_by_tail)


def create_live_stt_session(
    user: str, language: Optional[str] = None
) -> Dict[str, object]:
    return {
        "session_id": str(uuid.uuid4()),
        "user": user,
        "language": language,
        "committed_text": "",
        "mutable_text": "",
        "previous_hypothesis": "",
        "latest_hypothesis": "",
        "last_chunk_index": -1,
    }


def get_live_stt_session_key(session_id: str) -> str:
    return f"{LIVE_STT_SESSION_PREFIX}{session_id}"


def save_live_stt_session(redis_client, session_state: Dict[str, object]) -> None:
    redis_client.setex(
        get_live_stt_session_key(str(session_state["session_id"])),
        LIVE_STT_SESSION_TTL_SECONDS,
        json.dumps(session_state),
    )


def load_live_stt_session(redis_client, session_id: str) -> Optional[Dict[str, object]]:
    raw_session = redis_client.get(get_live_stt_session_key(session_id))
    if not raw_session:
        return None
    if isinstance(raw_session, bytes):
        raw_session = raw_session.decode("utf-8")
    return json.loads(raw_session)


def delete_live_stt_session(redis_client, session_id: str) -> None:
    redis_client.delete(get_live_stt_session_key(session_id))


def apply_live_stt_hypothesis(
    session_state: Dict[str, object],
    hypothesis_text: str,
    chunk_index: int,
    is_silence: bool = False,
) -> Dict[str, object]:
    last_chunk_index = int(session_state.get("last_chunk_index", -1))
    if chunk_index < 0:
        raise ValueError("chunk_index must be non-negative")
    if chunk_index < last_chunk_index:
        raise ValueError("chunk_index is older than the last processed chunk")
    if chunk_index == last_chunk_index:
        return session_state

    committed_text = normalize_transcript_text(str(session_state.get("committed_text", "")))
    previous_hypothesis = normalize_transcript_text(
        str(session_state.get("latest_hypothesis", ""))
    )
    current_hypothesis = strip_committed_prefix(committed_text, hypothesis_text)

    if not current_hypothesis and is_silence and previous_hypothesis:
        committed_text = join_transcript_parts(committed_text, previous_hypothesis)
        previous_hypothesis = ""

    commit_count = _calculate_commit_count(
        previous_hypothesis,
        current_hypothesis,
        is_silence=is_silence,
    )
    current_words = _split_words(current_hypothesis)

    if commit_count:
        committed_text = join_transcript_parts(
            committed_text,
            " ".join(current_words[:commit_count]),
        )
        current_hypothesis = " ".join(current_words[commit_count:])

    session_state["committed_text"] = committed_text
    session_state["mutable_text"] = normalize_transcript_text(current_hypothesis)
    session_state["previous_hypothesis"] = previous_hypothesis
    session_state["latest_hypothesis"] = normalize_transcript_text(current_hypothesis)
    session_state["last_chunk_index"] = chunk_index
    return session_state


def get_live_stt_transcript_text(session_state: Dict[str, object]) -> str:
    return join_transcript_parts(
        str(session_state.get("committed_text", "")),
        str(session_state.get("mutable_text", "")),
    )


def finalize_live_stt_session(session_state: Dict[str, object]) -> str:
    return join_transcript_parts(
        str(session_state.get("committed_text", "")),
        str(session_state.get("latest_hypothesis", "")),
    )
