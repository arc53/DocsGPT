"""
────────────────────────
test_oraclevectorstore.py
────────────────────────
Standalone integration test for OracleVectorStore.

What it tests (in order):
    1.  Connection          — can we reach Oracle 26ai with the wallet?
    2.  Table creation      — did LangChain create the table on first init?
    3.  Source-id index     — was the function-based index created?
    4.  add_texts()         — insert multiple chunks at once
    5.  add_chunk()         — insert a single chunk
    6.  get_chunks()        — fetch all chunks for this source_id
    7.  search()            — cosine similarity search
    8.  delete_chunk()      — delete one chunk by ID
    9.  Multi-tenant iso.   — source A cannot see source B's data
    10. delete_index()      — wipe all chunks for this source_id

"""

import os
import sys
import logging
import traceback

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oracle_test")

# ── Load .env manually (no dotenv dependency) ──────────────────────────────────
def _load_env(path=".env"):
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

_load_env()

# ── Colour helpers ─────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓  {msg}{RESET}")
def fail(msg): print(f"  {RED}✗  {msg}{RESET}")
def info(msg): print(f"  {YELLOW}→  {msg}{RESET}")

PASS = 0
FAIL = 0

def run(label, fn):
    """Run a single test case, catch any exception, report result."""
    global PASS, FAIL
    print(f"\n{'─'*60}")
    print(f"TEST: {label}")
    try:
        fn()
        ok("PASSED")
        PASS += 1
    except AssertionError as e:
        fail(f"FAILED — assertion: {e}")
        FAIL += 1
    except Exception as e:
        fail(f"FAILED — exception: {e}")
        traceback.print_exc()
        FAIL += 1


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

TEST_SOURCE_ID    = "test_source_abc123"
TEST_SOURCE_ID_B  = "test_source_xyz999"   # used for multi-tenant isolation test
TEST_TABLE        = "docsgpt_vectors"       # must match your .env / default

SAMPLE_TEXTS = [
    "Python is a high-level programming language known for its readability.",
    "Oracle Autonomous Database supports native VECTOR data type for AI workloads.",
    "LangChain is a framework for building LLM-powered applications.",
    "Vector similarity search finds the nearest neighbours in embedding space.",
    "pgvector is a PostgreSQL extension that adds vector column support.",
]

SAMPLE_METADATAS = [
    {"page": 1, "topic": "python"},
    {"page": 2, "topic": "oracle"},
    {"page": 3, "topic": "langchain"},
    {"page": 4, "topic": "vectors"},
    {"page": 5, "topic": "pgvector"},
]

store   = None   # OracleVectorStore instance (source A)
store_b = None   # OracleVectorStore instance (source B)


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — Connection + Init
# ══════════════════════════════════════════════════════════════════════════════

def test_01_connection_and_init():
    global store
    from application.vectorstore.oracle import OracleVectorStore

    store = OracleVectorStore(
        source_id=TEST_SOURCE_ID,
        table_name=TEST_TABLE,
    )
    assert store is not None, "OracleVectorStore returned None"
    assert store._connection is not None, "Raw oracledb connection is None after init"
    assert store._vectorstore is not None, "LangChain OracleVS is None after init"
    info(f"source_id = '{store._source_id}'")
    info(f"table     = '{store._table_name}'")


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — Table exists in Oracle
# ══════════════════════════════════════════════════════════════════════════════

def test_02_table_exists():
    conn   = store._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM user_tables WHERE table_name = :1",
        [TEST_TABLE.upper()],
    )
    count = cursor.fetchone()[0]
    cursor.close()
    assert count == 1, f"Table '{TEST_TABLE}' not found in user_tables"
    info(f"Table '{TEST_TABLE.upper()}' confirmed in user_tables.")


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — Source-id index exists
# ══════════════════════════════════════════════════════════════════════════════

def test_03_source_id_index():
    idx_name = f"{TEST_TABLE}_srcid_idx".upper()
    conn     = store._get_connection()
    cursor   = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM user_indexes WHERE index_name = :1",
        [idx_name],
    )
    count = cursor.fetchone()[0]
    cursor.close()
    assert count == 1, f"Index '{idx_name}' not found in user_indexes"
    info(f"Index '{idx_name}' confirmed.")


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — add_texts()
# ══════════════════════════════════════════════════════════════════════════════

inserted_ids = []

def test_04_add_texts():
    global inserted_ids
    ids = store.add_texts(texts=SAMPLE_TEXTS, metadatas=SAMPLE_METADATAS)
    assert ids, "add_texts() returned empty list"
    assert len(ids) == len(SAMPLE_TEXTS), (
        f"Expected {len(SAMPLE_TEXTS)} IDs, got {len(ids)}"
    )
    inserted_ids = ids
    info(f"Inserted {len(ids)} chunks. IDs: {ids}")


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — add_chunk()
# ══════════════════════════════════════════════════════════════════════════════

single_chunk_id = None

def test_05_add_chunk():
    global single_chunk_id
    chunk_id = store.add_chunk(
        text="DocsGPT is an open-source AI documentation assistant.",
        metadata={"page": 6, "topic": "docsgpt"},
    )
    assert chunk_id, "add_chunk() returned empty/None ID"
    single_chunk_id = chunk_id
    info(f"Single chunk inserted with ID: {chunk_id}")


# ══════════════════════════════════════════════════════════════════════════════
# Test 6 — get_chunks()
# ══════════════════════════════════════════════════════════════════════════════

def test_06_get_chunks():
    chunks = store.get_chunks()
    # We inserted 5 (add_texts) + 1 (add_chunk) = 6
    assert len(chunks) >= 6, (
        f"Expected at least 6 chunks, got {len(chunks)}"
    )
    for chunk in chunks:
        assert "doc_id"   in chunk, "Chunk missing 'doc_id'"
        assert "text"     in chunk, "Chunk missing 'text'"
        assert "metadata" in chunk, "Chunk missing 'metadata'"
        assert chunk["metadata"].get("source_id") == TEST_SOURCE_ID, (
            f"source_id mismatch in chunk metadata: {chunk['metadata']}"
        )
    info(f"get_chunks() returned {len(chunks)} chunks — all have correct source_id.")


# ══════════════════════════════════════════════════════════════════════════════
# Test 7 — search()
# ══════════════════════════════════════════════════════════════════════════════

def test_07_search():
    results = store.search(question="What is Oracle database?", k=3)
    assert results, "search() returned empty list"
    assert len(results) <= 3, f"Expected ≤3 results, got {len(results)}"

    for doc in results:
        assert hasattr(doc, "page_content"), "Result missing page_content"
        assert doc.page_content,            "Result has empty page_content"

    info(f"search() returned {len(results)} result(s):")
    for i, doc in enumerate(results, 1):
        preview = doc.page_content[:80].replace("\n", " ")
        info(f"  [{i}] {preview}...")


# ══════════════════════════════════════════════════════════════════════════════
# Test 8 — delete_chunk()
# ══════════════════════════════════════════════════════════════════════════════

def test_08_delete_chunk():
    assert single_chunk_id, "single_chunk_id not set — did test_05 pass?"

    # Delete the single chunk we added in test_05
    result = store.delete_chunk(single_chunk_id)
    assert result is True, f"delete_chunk() returned False for ID '{single_chunk_id}'"

    # Verify it's gone
    chunks = store.get_chunks()
    ids_left = [c["doc_id"] for c in chunks]
    assert single_chunk_id not in ids_left, (
        f"Chunk '{single_chunk_id}' still present after delete_chunk()"
    )
    info(f"Chunk '{single_chunk_id}' deleted and confirmed gone.")

    # Deleting it again should return False
    result2 = store.delete_chunk(single_chunk_id)
    assert result2 is False, "Deleting already-deleted chunk should return False"
    info("Double-delete correctly returned False.")


# ══════════════════════════════════════════════════════════════════════════════
# Test 9 — Multi-tenant isolation
# ══════════════════════════════════════════════════════════════════════════════

def test_09_multitenant_isolation():
    global store_b
    from application.vectorstore.oracle import OracleVectorStore

    # Source B — different source_id, same table
    store_b = OracleVectorStore(
        source_id=TEST_SOURCE_ID_B,
        table_name=TEST_TABLE,
    )
    store_b.add_texts(
        texts=["This chunk belongs exclusively to source B."],
        metadatas=[{"page": 1, "owner": "B"}],
    )

    # Source A should NOT see source B's chunks
    chunks_a = store.get_chunks()
    for chunk in chunks_a:
        assert chunk["metadata"].get("source_id") != TEST_SOURCE_ID_B, (
            "Source A can see Source B's chunks — isolation BROKEN!"
        )

    # Source B should NOT see source A's chunks
    chunks_b = store_b.get_chunks()
    for chunk in chunks_b:
        assert chunk["metadata"].get("source_id") != TEST_SOURCE_ID, (
            "Source B can see Source A's chunks — isolation BROKEN!"
        )

    info(f"Source A has {len(chunks_a)} chunks — none from Source B. ✓")
    info(f"Source B has {len(chunks_b)} chunks — none from Source A. ✓")

    # Cleanup source B
    store_b.delete_index()
    info("Source B cleaned up.")


# ══════════════════════════════════════════════════════════════════════════════
# Test 10 — delete_index()
# ══════════════════════════════════════════════════════════════════════════════

def test_10_delete_index():
    store.delete_index()

    chunks = store.get_chunks()
    assert len(chunks) == 0, (
        f"Expected 0 chunks after delete_index(), got {len(chunks)}"
    )
    info("delete_index() wiped all chunks for this source_id. Table still intact.")

    # Confirm the table itself still exists (only rows deleted, not table)
    conn   = store._get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM user_tables WHERE table_name = :1",
        [TEST_TABLE.upper()],
    )
    count = cursor.fetchone()[0]
    cursor.close()
    assert count == 1, "Table was dropped — delete_index() should only delete rows!"
    info("Table still exists after delete_index() — correct behaviour.")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 60)
    print("  OracleVectorStore — Integration Test Suite")
    print("═" * 60)

    run("1. Connection & Init",          test_01_connection_and_init)
    run("2. Table exists in Oracle",     test_02_table_exists)
    run("3. Source-id index exists",     test_03_source_id_index)
    run("4. add_texts()",                test_04_add_texts)
    run("5. add_chunk()",                test_05_add_chunk)
    run("6. get_chunks()",               test_06_get_chunks)
    run("7. search()",                   test_07_search)
    run("8. delete_chunk()",             test_08_delete_chunk)
    run("9. Multi-tenant isolation",     test_09_multitenant_isolation)
    run("10. delete_index()",            test_10_delete_index)

    print("\n" + "═" * 60)
    print(f"  Results:  {GREEN}{PASS} passed{RESET}  |  {RED}{FAIL} failed{RESET}")
    print("═" * 60 + "\n")

    sys.exit(0 if FAIL == 0 else 1)