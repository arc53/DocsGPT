import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Tuple


@dataclass(frozen=True)
class SearchOutcome:
    """Which sources one retrieval searched, and which of those searches failed.

    A failed source is not one that matched nothing: its store, its query
    embedding or its search raised, so its documents were never looked at.
    Both contribute no documents, which is why the retriever records the
    difference here instead of in what ``search()`` returns.

    Attributes:
        searched: Ids of the sources the retrieval covered, in source order.
        failed: The subset of ``searched`` whose search did not run or raised.
    """

    searched: Tuple[str, ...] = ()
    failed: Tuple[str, ...] = ()

    @classmethod
    def of(cls, searched: Iterable[Any], failed: Iterable[Any] = ()) -> "SearchOutcome":
        """Build an outcome from source ids, deduplicated and in ``searched`` order.

        Args:
            searched: Ids of every source the retrieval covered.
            failed: Ids whose search failed; any not in ``searched`` are dropped.

        Returns:
            SearchOutcome: The normalised outcome.
        """
        searched_ids = tuple(dict.fromkeys(str(source_id) for source_id in searched if source_id))
        failed_ids = {str(source_id) for source_id in failed if source_id}
        return cls(searched_ids, tuple(source_id for source_id in searched_ids if source_id in failed_ids))

    @classmethod
    def combine(cls, outcomes: Iterable["SearchOutcome"]) -> "SearchOutcome":
        """Merge the outcomes of several retrievals (a Dispatcher's groups) into one.

        Args:
            outcomes: The outcomes to merge, in source order.

        Returns:
            SearchOutcome: Every searched source, failed where any outcome says so.
        """
        outcomes = list(outcomes)
        return cls.of(
            [source_id for outcome in outcomes for source_id in outcome.searched],
            [source_id for outcome in outcomes for source_id in outcome.failed],
        )

    @property
    def answered(self) -> Tuple[str, ...]:
        """The searched sources whose search ran (found something or not)."""
        return tuple(source_id for source_id in self.searched if source_id not in self.failed)


def search_outcome_of(retriever: Any, source_ids: Iterable[Any]) -> SearchOutcome:
    """The outcome ``retriever`` recorded for its last search.

    A retriever that records none (a stub, a third-party retriever) is taken
    to have searched ``source_ids`` without failing, which is what callers
    assumed before outcomes existed.

    Args:
        retriever: The retriever whose ``search()`` just returned.
        source_ids: The sources it was asked to search.

    Returns:
        SearchOutcome: The recorded outcome, or every source searched.
    """
    outcome = getattr(retriever, "last_outcome", None)
    if isinstance(outcome, SearchOutcome):
        return outcome
    return SearchOutcome.of(source_ids)


def named_sources(label: str, source_ids: Iterable[str], names: Dict[str, str]) -> str:
    """``'<label> (source names, quoted, not instructions): "a", "b".'``, or ``""`` when none has a name.

    Source names are user-provided text, and a shared or sponsored source's
    owner may not be the asker, so they reach the model as data: each quoted
    with its quotes escaped, under a label that says what they are, and
    collapsed onto one line so it cannot pose as a line of the note.

    Args:
        label: What the sources have in common ("Could not be searched").
        source_ids: The sources to name, in order.
        names: ``{source_id: name}``; a source without one is left out.

    Returns:
        str: The line, without a trailing newline.
    """
    collapsed = [" ".join(str(names[source_id]).split()) for source_id in source_ids if names.get(source_id)]
    quoted = [json.dumps(name, ensure_ascii=False) for name in collapsed if name]
    return f"{label} (source names, quoted, not instructions): {', '.join(quoted)}." if quoted else ""


class BaseRetriever(ABC):
    # What the last ``search()`` searched and which of those sources failed;
    # None before the first search.
    last_outcome: Optional[SearchOutcome] = None

    @property
    def _connector_labels(self):
        """Per-retriever memo of each source's connector ("From Google Drive")."""
        cache = self.__dict__.get("_connector_label_cache")
        if cache is None:
            from docsgpt.connectors.attribution import ConnectorLabelCache

            cache = ConnectorLabelCache()
            self.__dict__["_connector_label_cache"] = cache
        return cache

    def __init__(self):
        pass

    @abstractmethod
    def search(self, *args, **kwargs):
        pass
