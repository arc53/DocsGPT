from unittest.mock import MagicMock, Mock, patch

import pytest


@pytest.mark.unit
class TestEmbeddingsWrapper:
    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_init_success(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 768
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("test-model")

        mock_st_cls.assert_called_once()
        assert wrapper.dimension == 768

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_init_failure(self, mock_st_cls):
        mock_st_cls.side_effect = Exception("model not found")

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        with pytest.raises(Exception, match="model not found"):
            EmbeddingsWrapper("bad-model")

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_init_none_model(self, mock_st_cls):
        mock_st_cls.return_value = None

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        with pytest.raises((ValueError, AttributeError)):
            EmbeddingsWrapper("bad-model")

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_init_null_first_module(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = None
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        with pytest.raises(ValueError, match="failed to load properly"):
            EmbeddingsWrapper("bad-model")

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_embed_query(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_model.encode.return_value = MagicMock(tolist=Mock(return_value=[0.1, 0.2, 0.3]))
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("model")
        result = wrapper.embed_query("hello world")

        mock_model.encode.assert_called_once_with("hello world")
        assert result == [0.1, 0.2, 0.3]

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_embed_documents(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_model.encode.return_value = MagicMock(
            tolist=Mock(return_value=[[0.1, 0.2], [0.3, 0.4]])
        )
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("model")
        result = wrapper.embed_documents(["doc1", "doc2"])

        mock_model.encode.assert_called_with(["doc1", "doc2"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_call_with_string(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_model.encode.return_value = MagicMock(tolist=Mock(return_value=[0.1]))
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("model")
        result = wrapper("hello")
        assert result == [0.1]

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_call_with_list(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_model.encode.return_value = MagicMock(
            tolist=Mock(return_value=[[0.1], [0.2]])
        )
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("model")
        result = wrapper(["a", "b"])
        assert result == [[0.1], [0.2]]

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_call_with_invalid_type(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 3
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        wrapper = EmbeddingsWrapper("model")
        with pytest.raises(ValueError, match="Input must be a string or a list"):
            wrapper(123)

    @patch("application.vectorstore.embeddings_local.SentenceTransformer")
    def test_trust_remote_code_default(self, mock_st_cls):
        mock_model = MagicMock()
        mock_model._first_module.return_value = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 768
        mock_st_cls.return_value = mock_model

        from application.vectorstore.embeddings_local import EmbeddingsWrapper

        EmbeddingsWrapper("model")

        call_kwargs = mock_st_cls.call_args[1]
        assert call_kwargs["trust_remote_code"] is True
