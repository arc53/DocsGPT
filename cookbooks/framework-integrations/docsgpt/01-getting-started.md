# Getting Started with DocsGPT + Valkey

**Beginner** · Python · ~15 min

## What is DocsGPT + Valkey?

[DocsGPT](https://github.com/arc53/DocsGPT) is an open-source AI assistant platform that lets you build intelligent agents with document retrieval (RAG). It supports pluggable vector store backends — FAISS, PostgreSQL, Elasticsearch, Qdrant, Milvus, and now **Valkey**.

Using Valkey as the vector store gives you:

* **Sub-millisecond vector search** — HNSW indexing with cosine similarity
* **Source isolation** — each document source gets its own filtered namespace
* **Simple deployment** — single Valkey instance handles both vector search and caching
* **No additional database** — if you already run Valkey for caching or sessions, reuse it for vectors

## Prerequisites

* Docker or Podman installed
* Python 3.10+
* Git

## Step 1: Start Valkey with Search Module

```bash
docker run -d --name valkey \
  -p 6379:6379 \
  valkey/valkey-bundle:latest
```

Verify the search module is loaded:

```bash
docker exec valkey valkey-cli MODULE LIST
# Should show "search" in the output
```

## Step 2: Clone and Configure DocsGPT

```bash
git clone https://github.com/arc53/DocsGPT.git
cd DocsGPT
```

Create your `.env` file:

```bash
cp .env-template .env
```

Edit `.env` and set:

```env
VECTOR_STORE=valkey
VALKEY_HOST=localhost
VALKEY_PORT=6379
```

## Step 3: Install Dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r application/requirements.txt
```

This installs `valkey-glide-sync` which provides the synchronous GLIDE client for Valkey.

## Step 4: Verify the Connection

```python
from glide_sync import GlideClient, GlideClientConfiguration, NodeAddress

config = GlideClientConfiguration(
    addresses=[NodeAddress(host="localhost", port=6379)]
)
client = GlideClient.create(config)
print(client.ping())  # b'PONG'
```

## Step 5: Run DocsGPT

Start the backend:

```bash
flask --app application/app.py run --host=0.0.0.0 --port=7091
```

DocsGPT will automatically create the Valkey search index on first use. You can now ingest documents through the UI or API — they'll be stored as vector embeddings in Valkey.

## How It Works Under the Hood

When you ingest a document, DocsGPT:

1. **Chunks** the document into passages
2. **Embeds** each chunk using the configured embedding model
3. **Stores** each chunk as a Valkey HASH with fields: `content`, `source_id`, `metadata`, `embedding`
4. **Indexes** the embeddings with an HNSW vector index via `FT.CREATE`

When you ask a question:

1. The query is embedded into a vector
2. `FT.SEARCH` performs KNN search filtered by `source_id`
3. Top-k results are returned as context for the LLM

| Operation | Valkey Command | What It Does |
|-----------|---------------|--------------|
| Create index | `FT.CREATE docsgpt ON HASH PREFIX doc: SCHEMA ...` | One-time index setup |
| Store chunk | `HSET doc:{uuid} content "..." source_id "..." embedding <bytes>` | Store document with vector |
| Search | `FT.SEARCH docsgpt @source_id:{id} =>[KNN k @embedding $BLOB]` | Vector similarity search |
| Delete source | `FT.SEARCH` + `DEL` per key | Remove all chunks for a source |

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `VECTOR_STORE` | `faiss` | Set to `valkey` to use Valkey |
| `VALKEY_HOST` | `localhost` | Valkey server hostname |
| `VALKEY_PORT` | `6379` | Valkey server port |
| `VALKEY_PASSWORD` | (none) | Password for authentication |
| `VALKEY_USE_TLS` | `false` | Enable TLS connections |
| `VALKEY_INDEX_NAME` | `docsgpt` | Name of the search index |
| `VALKEY_PREFIX` | `doc:` | Key prefix for document hashes |

[Next: 02 Document Ingestion & Retrieval →](02-ingestion-and-retrieval.md)
