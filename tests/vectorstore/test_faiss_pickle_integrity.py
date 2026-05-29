"""PoC + regression for CWE-502: tampered FAISS index.pkl rejected before pickle.load."""

import io
from unittest.mock import Mock, patch

import pytest


class _InMemoryStorage:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def file_exists(self, path: str) -> bool:
        return path in self.files

    def get_file(self, path: str):
        return io.BytesIO(self.files[path])

    def save_file(self, data, path: str, **_kwargs):
        if hasattr(data, "read"):
            self.files[path] = data.read()
        else:
            self.files[path] = bytes(data)
        return {"storage_type": "memory"}


@pytest.mark.unit
class TestFaissPickleIntegrity:
    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__(
            "application.vectorstore.base", fromlist=["BaseVectorStore"]
        ).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_tampered_pickle_is_rejected(
        self, mock_settings, mock_get_emb, mock_faiss
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.ENCRYPTION_SECRET_KEY = "test-secret"
        mock_get_emb.return_value = Mock(dimension=3)

        from application.vectorstore.faiss import _compute_signature

        storage = _InMemoryStorage()
        good_pkl = b"GENUINE_PICKLE_BYTES"
        storage.files["indexes/src1/index.faiss"] = b"FAISS_BLOB"
        storage.files["indexes/src1/index.pkl"] = good_pkl
        storage.files["indexes/src1/index.pkl.sig"] = _compute_signature(
            good_pkl
        ).encode("utf-8")

        # Attacker overwrites pickle but cannot forge HMAC.
        storage.files["indexes/src1/index.pkl"] = b"MALICIOUS_PICKLE_RCE"

        with patch(
            "application.vectorstore.faiss.StorageCreator"
        ) as mock_storage_creator:
            mock_storage_creator.get_storage.return_value = storage
            from application.vectorstore.faiss import FaissStore

            with pytest.raises(Exception, match="Error loading FAISS index"):
                FaissStore(source_id="src1", embeddings_key="k")

        mock_faiss.load_local.assert_not_called()

    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__(
            "application.vectorstore.base", fromlist=["BaseVectorStore"]
        ).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_valid_signature_loads_normally(
        self, mock_settings, mock_get_emb, mock_faiss
    ):
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.ENCRYPTION_SECRET_KEY = "test-secret"
        mock_get_emb.return_value = Mock(dimension=3)
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.load_local.return_value = mock_ds

        from application.vectorstore.faiss import _compute_signature

        storage = _InMemoryStorage()
        pkl_bytes = b"GENUINE_PICKLE_BYTES"
        storage.files["indexes/src2/index.faiss"] = b"FAISS_BLOB"
        storage.files["indexes/src2/index.pkl"] = pkl_bytes
        storage.files["indexes/src2/index.pkl.sig"] = _compute_signature(
            pkl_bytes
        ).encode("utf-8")

        with patch(
            "application.vectorstore.faiss.StorageCreator"
        ) as mock_storage_creator:
            mock_storage_creator.get_storage.return_value = storage
            from application.vectorstore.faiss import FaissStore

            store = FaissStore(source_id="src2", embeddings_key="k")

        mock_faiss.load_local.assert_called_once()
        assert store.docsearch is mock_ds

    @patch("application.vectorstore.faiss.FAISS")
    @patch.object(
        __import__(
            "application.vectorstore.base", fromlist=["BaseVectorStore"]
        ).BaseVectorStore,
        "_get_embeddings",
    )
    @patch("application.vectorstore.faiss.settings")
    def test_legacy_index_without_sig_is_signed_tofu(
        self, mock_settings, mock_get_emb, mock_faiss
    ):
        """Backward compatibility: legacy indexes without a sig file are
        accepted once and a TOFU signature is persisted."""
        mock_settings.EMBEDDINGS_NAME = "test_model"
        mock_settings.ENCRYPTION_SECRET_KEY = "test-secret"
        mock_get_emb.return_value = Mock(dimension=3)
        mock_ds = Mock()
        mock_ds.index = Mock(d=3)
        mock_faiss.load_local.return_value = mock_ds

        storage = _InMemoryStorage()
        storage.files["indexes/src3/index.faiss"] = b"FAISS_BLOB"
        storage.files["indexes/src3/index.pkl"] = b"LEGACY_PICKLE"

        with patch(
            "application.vectorstore.faiss.StorageCreator"
        ) as mock_storage_creator:
            mock_storage_creator.get_storage.return_value = storage
            from application.vectorstore.faiss import FaissStore, _compute_signature

            FaissStore(source_id="src3", embeddings_key="k")

        assert "indexes/src3/index.pkl.sig" in storage.files
        assert storage.files["indexes/src3/index.pkl.sig"].decode() == _compute_signature(
            b"LEGACY_PICKLE"
        )
        mock_faiss.load_local.assert_called_once()
