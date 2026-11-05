"""Safety limits shared by chunking and embedding ingestion paths."""

# Self-attention memory grows quadratically with input length. Keep chunk
# configuration and every ingest-time embedding input below a safe hard cap.
MAX_CHUNK_TOKENS = 4096

# Bound the number of sentence vectors SemanticChunker asks for at once. This
# limits request size for remote providers and peak memory for local models.
SEMANTIC_EMBED_BATCH_SIZE = 32
