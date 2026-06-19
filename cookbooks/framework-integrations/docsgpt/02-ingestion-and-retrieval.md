# Document Ingestion & Retrieval

**Intermediate** · Python · ~20 min

## Overview

This cookbook walks through the DocsGPT + Valkey vector store internals — how documents are chunked, embedded, stored in Valkey as HASH objects with HNSW-indexed vectors, and retrieved via filtered KNN search. You'll use the `ValkeyStore` class directly to understand each step.

## Prerequisites

* Completed [01 - Getting Started](01-getting-started.md)
* Valkey running with the search module loaded
* DocsGPT dependencies installed

## Step 1: Create a ValkeyStore Instance

```python
import os
os.environ["VECTOR_STORE"] = "valkey"
os.environ["VALKEY_HOST"] = "localhost"
os.environ["VALKEY_PORT"] = "6379"

from application.vectorstore.valkey import ValkeyStore

# Each source_id isolates a set of documents
store = ValkeyStore(source_id="my-docs", embeddings_key="embeddings")
```

On creation, `ValkeyStore`:
1. Connects to Valkey using the synchronous GLIDE client
2. Creates an HNSW index (if it doesn't exist) with schema:
   - `content` — TEXT field (full-text searchable)
   - `source_id` — TAG field (exact match filtering)
   - `embedding` — VECTOR field (HNSW, cosine distance, FLOAT32)

## Step 2: Ingest Documents

### Bulk ingestion with `add_texts`

```python
texts = [
    "Valkey is a high-performance in-memory data store.",
    "Vector search uses HNSW algorithm for approximate nearest neighbors.",
    "DocsGPT supports multiple vector store backends including Valkey.",
    "The GLIDE client provides both async and sync interfaces for Valkey.",
]

metadatas = [
    {"source": "valkey-docs.pdf", "page": 1},
    {"source": "valkey-docs.pdf", "page": 5},
    {"source": "docsgpt-readme.md", "page": 1},
    {"source": "glide-docs.md", "page": 1},
]

doc_ids = store.add_texts(texts, metadatas)
print(f"Ingested {len(doc_ids)} documents: {doc_ids}")
```

Each document is stored as a Valkey HASH:

```
HSET doc:<uuid> content "Valkey is a high..." source_id "my-docs" metadata '{"source":"valkey-docs.pdf","page":1}' embedding <768 floats as bytes>
```

### Single chunk with `add_chunk`

```python
chunk_id = store.add_chunk(
    text="Valkey Search supports KNN queries with pre-filtering.",
    metadata={"source": "search-guide.md", "section": "queries"},
)
print(f"Added chunk: {chunk_id}")
```

## Step 3: Search by Semantic Similarity

```python
results = store.search("How does vector search work?", k=3)

for doc in results:
    print(f"Content: {doc.page_content[:80]}...")
    print(f"Metadata: {doc.metadata}")
    print()
```

Under the hood, this:
1. Embeds the query text into a vector
2. Executes: `FT.SEARCH docsgpt "@source_id:{my-docs} =>[KNN 3 @embedding $BLOB AS score]"`
3. Returns documents ranked by cosine similarity

### Source Isolation

Each `source_id` is a TAG field filter. Multiple document sources share the same index but never mix in search results:

```python
# Only searches within "my-docs" source
store_a = ValkeyStore(source_id="project-a")
store_b = ValkeyStore(source_id="project-b")

# These searches are completely isolated
results_a = store_a.search("deployment guide")
results_b = store_b.search("deployment guide")
```

## Step 4: Manage Chunks

### List all chunks for a source

```python
chunks = store.get_chunks()
print(f"Total chunks: {len(chunks)}")
for chunk in chunks:
    print(f"  ID: {chunk['doc_id']}, Text: {chunk['text'][:50]}...")
```

### Delete a specific chunk

```python
success = store.delete_chunk(doc_ids[0])
print(f"Deleted: {success}")  # True
```

### Delete all chunks for a source

```python
store.delete_index()
# All documents with source_id="my-docs" are removed
```

## Step 5: Production Deployment with Docker Compose

```yaml
services:
  valkey:
    image: valkey/valkey-bundle:latest
    ports:
      - "6379:6379"
    volumes:
      - valkey_data:/data

  docsgpt-backend:
    build: ./application
    environment:
      - VECTOR_STORE=valkey
      - VALKEY_HOST=valkey
      - VALKEY_PORT=6379
    depends_on:
      - valkey

volumes:
  valkey_data:
```

## Performance Characteristics

| Operation | Complexity | Typical Latency |
|-----------|-----------|----------------|
| `add_texts` (per doc) | O(log n) HNSW insert | ~1-2ms |
| `search` (KNN) | O(log n) HNSW search | <1ms |
| `delete_chunk` | O(1) key delete | <0.1ms |
| `get_chunks` | O(n) for source | ~1ms per 100 docs |
| `delete_index` | O(n) search + delete | Depends on doc count |

## Index Configuration

The default HNSW parameters work well for most use cases. The index is created once and backfilled automatically:

```python
VectorField(
    name="embedding",
    algorithm=VectorAlgorithm.HNSW,
    attributes=VectorFieldAttributesHnsw(
        dimensions=768,              # Matches embedding model output
        distance_metric=DistanceMetricType.COSINE,
        type=VectorType.FLOAT32,
    ),
)
```

For larger datasets (>1M vectors), consider tuning HNSW parameters like `number_of_edges` and `vectors_examined_on_construction` for your recall/latency tradeoff.

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `ImportError: valkey-glide-sync` | Package not installed | `pip install valkey-glide-sync` |
| `Connection refused` | Valkey not running | Start Valkey container |
| `unknown command FT.CREATE` | Search module not loaded | Add `--loadmodule` flag to Valkey startup |
| Empty search results | Wrong `source_id` | Verify source_id matches what was used during ingestion |

[← Back: 01 Getting Started](01-getting-started.md)
