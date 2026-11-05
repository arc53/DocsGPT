"""MilvusStore chunk deletes stay in their source, checked against a mocked client.

``test_milvus.py`` drives a real Milvus Lite, which isn't available on every
platform; these run everywhere.
"""

from unittest.mock import MagicMock

import pytest


def _store(source_id="src-A"):
    from docsgpt.vectorstore.milvus import MilvusStore

    store = MilvusStore.__new__(MilvusStore)
    store._source_id = source_id
    store._collection = "c"
    store._client = MagicMock()
    return store


@pytest.mark.unit
class TestMilvusChunkDeletesStayInTheirSource:
    def test_delete_chunk_is_filtered_on_the_source(self):
        store = _store()
        store._client.query.return_value = [{"id": "x1"}]

        assert store.delete_chunk("x1") is True

        delete = store._client.delete.call_args.kwargs
        assert "ids" not in delete
        assert delete["filter"] == 'id in ["x1"] and source_id == "src-A"'
        assert store._client.query.call_args.kwargs["filter"] == delete["filter"]

    def test_another_sources_chunk_is_not_deleted(self):
        store = _store()
        store._client.query.return_value = []

        assert store.delete_chunk("victim") is False
        store._client.delete.assert_not_called()

    def test_delete_chunks_counts_only_this_sources(self):
        store = _store()
        store._client.query.return_value = [{"id": "a"}]

        assert store.delete_chunks(["a", "b", "a"]) == 1

        assert store._client.delete.call_args.kwargs["filter"] == 'id in ["a"] and source_id == "src-A"'

    def test_an_id_cannot_break_out_of_the_expression(self):
        store = _store()
        store._client.query.return_value = []

        store.delete_chunk('x"] or source_id != "')

        expression = store._client.query.call_args.kwargs["filter"]
        assert expression == 'id in ["x\\"] or source_id != \\""] and source_id == "src-A"'

    def test_a_client_error_is_false(self):
        store = _store()
        store._client.query.side_effect = RuntimeError("milvus down")

        assert store.delete_chunk("x1") is False
        assert store.delete_chunks(["x1"]) == 0

    def test_update_of_another_sources_chunk_is_refused_and_leaves_nothing(self):
        store = _store()
        store._embeddings = MagicMock()
        store._embeddings.embed_documents.return_value = [[0.1, 0.2]]
        store._client.query.return_value = []

        with pytest.raises(RuntimeError, match="Failed to delete old chunk"):
            store.update_chunk("victim", "PWNED", {})

        # The chunk the update added to this source was taken out again.
        [inserted] = store._client.insert.call_args.kwargs["data"]
        assert store._client.query.call_args_list[-1].kwargs["filter"].startswith(f'id in ["{inserted["id"]}"]')
