# ruff: noqa: E402
"""Benchmark prototype for DocsGPT Issue #2578: Extractive Boilerplate Pruning.

Evaluates standalone chunk-level context token savings, execution latency, and
structural fidelity (complete code blocks, full markdown table rows, warnings,
navigation removal, and duplicate header deduplication) against exact document
source IDs. Compares unpruned baseline chunks and in-tree boilerplate pruning
(zero dependencies) over representative queries with observed percentage calculations.

Note: This benchmark evaluates standalone retrieved chunk tokens and structural
preservation. It does not evaluate full-prompt token costs, LLM generated-answer
accuracy, or downstream citation support.
"""

from __future__ import annotations

import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docsgpt.retriever.stages.boilerplate_pruning import prune_boilerplate
from docsgpt.utils import get_encoding

# Ground truth representative corpus across 3 source IDs with explicit structural specs
REPRESENTATIVE_CORPUS: List[Dict[str, Any]] = [
    {
        "id": "doc_api_overview",
        "title": "DocsGPT API Overview",
        "source": "https://docs.docsgpt.cloud/api/overview",
        "text": (
            "Home > Documentation > API Reference > Overview\n"
            "DocsGPT API Documentation v2.4\n"
            "# Table of Contents\n"
            "DocsGPT provides a unified REST API for conversational document retrieval and question answering.\n"
            "All API requests must include the `Authorization: Bearer <TOKEN>` header in HTTP requests.\n"
            "On this page\n"
            "Never expose API secret keys in client-side code or public repositories.\n"
            "| Parameter | Type | Required | Description |\n"
            "| --- | --- | --- | --- |\n"
            "| question | string | true | The end-user inquiry to answer |\n"
            "| sources | array | false | Filter specific document vectorstores |\n"
            "Next page: Stream Endpoints\n"
            "Edit this page on GitHub"
        ),
        "expected_code_block": None,
        "expected_table_rows": [
            "| Parameter | Type | Required | Description |",
            "| --- | --- | --- | --- |",
            "| question | string | true | The end-user inquiry to answer |",
            "| sources | array | false | Filter specific document vectorstores |",
        ],
        "expected_warnings": [
            "Never expose API secret keys in client-side code or public repositories.",
            "All API requests must include the `Authorization: Bearer <TOKEN>` header in HTTP requests.",
        ],
        "nav_lines": [
            "Home > Documentation > API Reference > Overview",
            "# Table of Contents",
            "On this page",
            "Next page: Stream Endpoints",
            "Edit this page on GitHub",
        ],
        "is_duplicate_header": False,  # First occurrence: retained
    },
    {
        "id": "doc_stream_endpoint",
        "title": "DocsGPT Streaming Endpoints",
        "source": "https://docs.docsgpt.cloud/api/streaming",
        "text": (
            "Home > Documentation > API Reference > Streaming\n"
            "DocsGPT API Documentation v2.4\n"
            "Streaming responses are delivered over Server-Sent Events (SSE) via the `/api/answer` route.\n"
            "To initiate a stream using cURL, execute the following command:\n"
            "```bash\n"
            "curl -X POST https://api.docsgpt.cloud/api/answer \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            '  -d \'{"question": "How do I configure vectorstores?"}\'\n'
            "```\n"
            "Clients must handle premature disconnects gracefully; the worker does not buffer unconsumed frames.\n"
            "Quick Links\n"
            "Was this article helpful?\n"
            "Previous page: Overview\n"
            "Next page: Connectors"
        ),
        "expected_code_block": (
            "```bash\n"
            "curl -X POST https://api.docsgpt.cloud/api/answer \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            '  -d \'{"question": "How do I configure vectorstores?"}\'\n'
            "```"
        ),
        "expected_table_rows": [],
        "expected_warnings": [
            "Clients must handle premature disconnects gracefully; the worker does not buffer unconsumed frames.",
        ],
        "nav_lines": [
            "Home > Documentation > API Reference > Streaming",
            "Quick Links",
            "Was this article helpful?",
            "Previous page: Overview",
            "Next page: Connectors",
        ],
        "is_duplicate_header": True,  # Repeated header: deduplicated
    },
    {
        "id": "doc_connector_setup",
        "title": "DocsGPT Vectorstore Connectors",
        "source": "https://docs.docsgpt.cloud/connectors/pgvector",
        "text": (
            "Home > Connectors > PostgreSQL > PGVector\n"
            "DocsGPT API Documentation v2.4\n"
            "# On this page\n"
            "The PGVector connector stores document embeddings directly in PostgreSQL using the HNSW index type.\n"
            "```sql\n"
            "CREATE EXTENSION IF NOT EXISTS vector;\n"
            "CREATE TABLE docsgpt_embeddings (id uuid PRIMARY KEY, embedding vector(1536));\n"
            "```\n"
            "Deprecation Warning: The legacy IVFFlat index type is deprecated; use HNSW for all production clusters.\n"
            "Back to top\n"
            "Skip to main content"
        ),
        "expected_code_block": (
            "```sql\n"
            "CREATE EXTENSION IF NOT EXISTS vector;\n"
            "CREATE TABLE docsgpt_embeddings (id uuid PRIMARY KEY, embedding vector(1536));\n"
            "```"
        ),
        "expected_table_rows": [],
        "expected_warnings": [
            "Deprecation Warning: The legacy IVFFlat index type is deprecated; use HNSW for all production clusters.",
        ],
        "nav_lines": [
            "Home > Connectors > PostgreSQL > PGVector",
            "# On this page",
            "Back to top",
            "Skip to main content",
        ],
        "is_duplicate_header": True,  # Repeated header: deduplicated
    },
]

DUPLICATE_HEADER_TEXT = "DocsGPT API Documentation v2.4"

BENCHMARK_QUERIES: List[str] = [
    "What header is required for DocsGPT API requests?",
    "How do I stream answers via cURL?",
    "Which PostgreSQL vector index type is recommended?",
]


def evaluate_structural_integrity(
    output_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluates complete code blocks, complete table rows, warnings, nav removal, and header deduplication

    strictly checked against each document's source ID.
    """
    doc_map = {d.get("id"): d.get("text", "") for d in output_docs}

    code_expected = 0
    code_preserved = 0
    table_rows_expected = 0
    table_rows_preserved = 0
    warnings_expected = 0
    warnings_preserved = 0
    nav_lines_expected = 0
    nav_lines_removed = 0
    dup_headers_expected = 0
    dup_headers_removed = 0

    order_intact = [d["id"] for d in output_docs] == [d["id"] for d in REPRESENTATIVE_CORPUS]

    for item in REPRESENTATIVE_CORPUS:
        doc_id = item["id"]
        doc_text = doc_map.get(doc_id, "")

        # 1. Complete code block checked against source ID
        if item["expected_code_block"]:
            code_expected += 1
            if item["expected_code_block"] in doc_text:
                code_preserved += 1

        # 2. Complete table rows checked against source ID
        for row in item["expected_table_rows"]:
            table_rows_expected += 1
            if row in doc_text:
                table_rows_preserved += 1

        # 3. Expected warnings checked against source ID
        for warning in item["expected_warnings"]:
            warnings_expected += 1
            if warning in doc_text:
                warnings_preserved += 1

        # 4. Navigation line removals checked against source ID
        for nav in item["nav_lines"]:
            nav_lines_expected += 1
            if nav not in doc_text:
                nav_lines_removed += 1

        # 5. Duplicate header deduplication checked against source ID
        if item["is_duplicate_header"]:
            dup_headers_expected += 1
            if DUPLICATE_HEADER_TEXT not in doc_text:
                dup_headers_removed += 1

    return {
        "order_intact": order_intact,
        "code_expected": code_expected,
        "code_preserved": code_preserved,
        "table_rows_expected": table_rows_expected,
        "table_rows_preserved": table_rows_preserved,
        "warnings_expected": warnings_expected,
        "warnings_preserved": warnings_preserved,
        "nav_lines_expected": nav_lines_expected,
        "nav_lines_removed": nav_lines_removed,
        "dup_headers_expected": dup_headers_expected,
        "dup_headers_removed": dup_headers_removed,
    }


def run_benchmark() -> None:
    enc = get_encoding()
    queries = BENCHMARK_QUERIES

    print("=" * 78)
    print("  DocsGPT Benchmark Prototype: Boilerplate Pruning (Issue #2578)")
    print("=" * 78)
    print()

    # Metrics storage
    baseline_tokens_list: List[int] = []
    intree_tokens_list: List[int] = []
    intree_latencies_ms: List[float] = []

    intree_eval_totals = {
        "code_exp": 0,
        "code_pres": 0,
        "table_exp": 0,
        "table_pres": 0,
        "warn_exp": 0,
        "warn_pres": 0,
        "nav_exp": 0,
        "nav_rem": 0,
        "dup_exp": 0,
        "dup_rem": 0,
        "order_matches": 0,
    }

    # Run over queries
    for query in queries:
        # A. Baseline
        raw_docs = deepcopy(REPRESENTATIVE_CORPUS)
        base_tokens = sum(len(enc.encode(d["text"])) for d in raw_docs)
        baseline_tokens_list.append(base_tokens)

        # B. In-Tree Pruning
        t0 = time.perf_counter()
        intree_docs = prune_boilerplate(deepcopy(REPRESENTATIVE_CORPUS), query=query)
        t_intree = (time.perf_counter() - t0) * 1000
        intree_tokens = sum(len(enc.encode(d["text"])) for d in intree_docs)
        intree_tokens_list.append(intree_tokens)
        intree_latencies_ms.append(t_intree)

        intree_eval = evaluate_structural_integrity(intree_docs)
        intree_eval_totals["code_exp"] += intree_eval["code_expected"]
        intree_eval_totals["code_pres"] += intree_eval["code_preserved"]
        intree_eval_totals["table_exp"] += intree_eval["table_rows_expected"]
        intree_eval_totals["table_pres"] += intree_eval["table_rows_preserved"]
        intree_eval_totals["warn_exp"] += intree_eval["warnings_expected"]
        intree_eval_totals["warn_pres"] += intree_eval["warnings_preserved"]
        intree_eval_totals["nav_exp"] += intree_eval["nav_lines_expected"]
        intree_eval_totals["nav_rem"] += intree_eval["nav_lines_removed"]
        intree_eval_totals["dup_exp"] += intree_eval["dup_headers_expected"]
        intree_eval_totals["dup_rem"] += intree_eval["dup_headers_removed"]
        if intree_eval["order_intact"]:
            intree_eval_totals["order_matches"] += 1

    # Calculate observed percentages (never hardcoded)
    avg_base_tokens = sum(baseline_tokens_list) // len(queries)
    avg_intree_tokens = sum(intree_tokens_list) // len(queries)
    avg_intree_latency_ms = sum(intree_latencies_ms) / len(intree_latencies_ms)
    intree_savings_pct = (
        ((sum(baseline_tokens_list) - sum(intree_tokens_list)) / sum(baseline_tokens_list)) * 100
        if sum(baseline_tokens_list)
        else 0.0
    )

    intree_code_pct = (
        (intree_eval_totals["code_pres"] / intree_eval_totals["code_exp"]) * 100
        if intree_eval_totals["code_exp"]
        else 100.0
    )
    intree_table_pct = (
        (intree_eval_totals["table_pres"] / intree_eval_totals["table_exp"]) * 100
        if intree_eval_totals["table_exp"]
        else 100.0
    )
    intree_warn_pct = (
        (intree_eval_totals["warn_pres"] / intree_eval_totals["warn_exp"]) * 100
        if intree_eval_totals["warn_exp"]
        else 100.0
    )
    intree_nav_pct = (
        (intree_eval_totals["nav_rem"] / intree_eval_totals["nav_exp"]) * 100
        if intree_eval_totals["nav_exp"]
        else 100.0
    )
    intree_dup_pct = (
        (intree_eval_totals["dup_rem"] / intree_eval_totals["dup_exp"]) * 100
        if intree_eval_totals["dup_exp"]
        else 100.0
    )
    intree_order_pct = (intree_eval_totals["order_matches"] / len(queries)) * 100

    print("### 1. Token Cost & Latency Comparison across Queries")
    print(f"- **Baseline Context Tokens (OFF):** {avg_base_tokens} tokens / query")
    print(f"- **In-Tree Pruned Tokens (ON):**     {avg_intree_tokens} tokens / query")
    print(
        f"- **Token Savings:**                 "
        f"{sum(baseline_tokens_list) - sum(intree_tokens_list)} tokens across {len(queries)} queries ({intree_savings_pct:.1f}% reduction)"
    )
    print(f"- **In-Memory Pruning Latency:**     {avg_intree_latency_ms:.2f} ms per retrieval")
    print()

    print("### 2. Semantic & Structural Integrity (Calculated from Observed Results)")
    print(
        f"- **Document Order & Inclusion:**    {intree_order_pct:.1f}% Intact "
        f"({intree_eval_totals['order_matches']}/{len(queries)} queries)"
    )
    print(
        f"- **Complete Code Blocks Preserved:** {intree_code_pct:.1f}% "
        f"({intree_eval_totals['code_pres']}/{intree_eval_totals['code_exp']} across queries)"
    )
    print(
        f"- **Complete Table Rows Preserved:** {intree_table_pct:.1f}% "
        f"({intree_eval_totals['table_pres']}/{intree_eval_totals['table_exp']} rows across queries)"
    )
    print(
        f"- **Negations & Warnings Preserved:** {intree_warn_pct:.1f}% "
        f"({intree_eval_totals['warn_pres']}/{intree_eval_totals['warn_exp']} warnings across queries)"
    )
    print(
        f"- **Navigation Lines Removed:**      {intree_nav_pct:.1f}% "
        f"({intree_eval_totals['nav_rem']}/{intree_eval_totals['nav_exp']} lines removed across queries)"
    )
    print(
        f"- **Duplicate Headers Deduplicated:** {intree_dup_pct:.1f}% "
        f"({intree_eval_totals['dup_rem']}/{intree_eval_totals['dup_exp']} headers deduplicated across queries)"
    )
    print()

    # Markdown Results Table with observed percentages
    table = [
        "| Metric | Baseline (Unpruned Chunks) | In-Tree Pruning (Zero Dependencies) |",
        "| :--- | :--- | :--- |",
        f"| **Context Tokens / Query** | {avg_base_tokens} | {avg_intree_tokens} (-{intree_savings_pct:.1f}%) |",
        f"| **Processing Latency** | Baseline (0.0 ms) | +{avg_intree_latency_ms:.2f} ms |",
        f"| **Complete Code Block Fidelity** | 100.0% | {intree_code_pct:.1f}% ({intree_eval_totals['code_pres']}/{intree_eval_totals['code_exp']}) |",
        f"| **Complete Table Rows Fidelity** | 100.0% | {intree_table_pct:.1f}% ({intree_eval_totals['table_pres']}/{intree_eval_totals['table_exp']}) |",
        f"| **Factual Warnings & Negations** | 100.0% | {intree_warn_pct:.1f}% ({intree_eval_totals['warn_pres']}/{intree_eval_totals['warn_exp']}) |",
        f"| **Navigation Lines Removed** | 0.0% (0/{intree_eval_totals['nav_exp']}) | {intree_nav_pct:.1f}% ({intree_eval_totals['nav_rem']}/{intree_eval_totals['nav_exp']}) |",
        f"| **Duplicate Header Deduplication** | 0.0% (0/{intree_eval_totals['dup_exp']}) | {intree_dup_pct:.1f}% ({intree_eval_totals['dup_rem']}/{intree_eval_totals['dup_exp']}) |",
        f"| **Document IDs & Order** | 100.0% | {intree_order_pct:.1f}% Intact |",
        "| **External Dependencies Required** | None | None (Standard Library Only) |",
    ]
    print("\n".join(table))
    print(
        "\n*Note: Standalone prototype evaluating retrieved chunk tokens and syntax integrity. "
        "Does not measure full-prompt cost, generated-answer accuracy, or citation support.*"
    )


if __name__ == "__main__":
    run_benchmark()
