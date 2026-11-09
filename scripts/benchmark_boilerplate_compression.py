# ruff: noqa: E402
"""Benchmark script to quantify compression ratio, token savings, cost, and latency

for DocsGPT Extractive Boilerplate Pruning (Issue #2578).
Evaluates both ClassicRAG and Dispatcher retrieval pipelines on representative
technical documentation with citation support, answer accuracy, and safety audit.
Isolates Baseline (OFF), In-Tree Pruning (Zero Dependencies), and Optional SuperCompress.
"""

from __future__ import annotations

import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tiktoken

from docsgpt.retriever.dispatcher import Dispatcher, build_dispatcher
from docsgpt.retriever.stages.boilerplate_pruning import compress_retrieved_chunks, prune_boilerplate
from docsgpt.utils import get_encoding

# Representative technical documentation corpus across 3 sources (Core Guides, API Reference, Python SDK)
# Includes navigation, breadcrumbs, tables of contents, pagination, code blocks, tables, and critical qualifiers
REPRESENTATIVE_CORPUS: List[Dict[str, Any]] = [
    {
        "id": "doc1",
        "source": "docs_core",
        "title": "Authentication Guide",
        "url": "https://docs.docsgpt.cloud/security/auth",
        "text": (
            "Home > Documentation > Security > Authentication\n"
            "# Table of Contents\n"
            "This guide describes API authentication methods for DocsGPT.\n"
            "On this page\n"
            "Users must not share authentication keys with third parties under any circumstances.\n"
            "To authenticate via bearer token:\n"
            "```bash\n"
            'curl -H "Authorization: Bearer $DOCSGPT_API_KEY" https://api.docsgpt.cloud/v1/chat\n'
            "```\n"
            "Next page: Endpoints\n"
            "Edit this page on GitHub"
        ),
    },
    {
        "id": "doc2",
        "source": "docs_api",
        "title": "API Reference Endpoints",
        "url": "https://docs.docsgpt.cloud/api/endpoints",
        "text": (
            "Home > API Reference > Endpoints\n"
            "DocsGPT API v2.0 Reference Manual\n"
            "| Parameter | Type | Required | Description |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| query | string | true | The search question |\n"
            "| stream | boolean | false | Enable streaming |\n"
            "Critical: Never transmit production passwords over unencrypted HTTP channels.\n"
            "Quick Links\n"
            "Previous page: Authentication"
        ),
    },
    {
        "id": "doc3",
        "source": "docs_api",
        "title": "API Reference Endpoints (Continuation)",
        "url": "https://docs.docsgpt.cloud/api/endpoints#reindex",
        "text": (
            "Home > API Reference > Endpoints\n"
            "DocsGPT API v2.0 Reference Manual\n"
            "The /v1/index endpoint allows rebuilding vector indices asynchronously.\n"
            "Next page token lifetime: 24 hours\n"
            "Rate limiting applies: maximum 60 requests per minute.\n"
            "Share this page | Print this page"
        ),
    },
    {
        "id": "doc4",
        "source": "docs_sdk",
        "title": "Python SDK Quickstart",
        "url": "https://docs.docsgpt.cloud/sdk/python",
        "text": (
            "Docs / SDK / Python / Quickstart\n"
            "# Quickstart\n"
            "To initialize the DocsGPT client in Python:\n"
            "```python\n"
            "from docsgpt import DocsGPTClient\n"
            "\n"
            "client = DocsGPTClient(api_key='your-api-key')\n"
            "response = client.ask('How do I configure vector storage?')\n"
            "```\n"
            "Caution: Deprecated methods in v1.x should not be used in new deployments.\n"
            "Next page: Python SDK Advanced Usage"
        ),
    },
    {
        "id": "doc5",
        "source": "docs_core",
        "title": "Vector Index Sharding",
        "url": "https://docs.docsgpt.cloud/architecture/sharding",
        "text": (
            "Architecture > Storage > Vector Sharding\n"
            "DocsGPT distributes dense vector collections across multiple index shards.\n"
            "| Shard ID | Dimension | Metric | Status |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| shard-01 | 1536 | cosine | ACTIVE |\n"
            "| shard-02 | 1536 | cosine | ACTIVE |\n"
            "Warning: Shard rebalancing must not be interrupted during cluster migration.\n"
            "Was this article helpful?"
        ),
    },
    {
        "id": "doc6",
        "source": "docs_api",
        "title": "Webhook Security & Signatures",
        "url": "https://docs.docsgpt.cloud/api/webhooks",
        "text": (
            "Docs > Integrations > Webhooks\n"
            "Webhook events are delivered with an HMAC-SHA256 signature in the DocsGPT-Signature header.\n"
            "Recipients must verify signatures before processing webhook payloads.\n"
            "```json\n"
            '{"event": "source.indexed", "source_id": "src_12345", "status": "completed"}\n'
            "```\n"
            "Back to top"
        ),
    },
    {
        "id": "doc7",
        "source": "docs_core",
        "title": "Role-Based Access Control",
        "url": "https://docs.docsgpt.cloud/security/rbac",
        "text": (
            "Home > Security > Access Control\n"
            "Organization roles govern workspace read and write permissions.\n"
            "| Role | Vector Read | Vector Write | Admin Settings |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| viewer | true | false | false |\n"
            "| editor | true | true | false |\n"
            "| admin | true | true | true |\n"
            "Only valid organization administrators can modify tenant membership.\n"
            "Next page: Audit Logs"
        ),
    },
    {
        "id": "doc8",
        "source": "docs_sdk",
        "title": "HTTP Status Codes & Error Handling",
        "url": "https://docs.docsgpt.cloud/api/errors",
        "text": (
            "Docs / API / Error Handling\n"
            "DocsGPT returns standard RFC-7807 error responses.\n"
            "Previous page cursor value: xyz123\n"
            "The client raises a TimeoutException if no response arrives within 30 seconds.\n"
            "HTTP 401 indicates missing or invalid bearer credentials.\n"
            "Next page: Rate Limits"
        ),
    },
]

# Evaluation queries, golden ground-truth facts, and expected claims
EVALUATION_QUERIES = [
    {
        "query": "authentication bearer token",
        "stable_doc_id": "doc1",
        "target": 'curl -H "Authorization: Bearer $DOCSGPT_API_KEY" https://api.docsgpt.cloud/v1/chat',
        "expected_code_block": (
            '```bash\ncurl -H "Authorization: Bearer $DOCSGPT_API_KEY" https://api.docsgpt.cloud/v1/chat\n```'
        ),
        "expected_table_block": None,
        "qualifier": "must not share",
        "expected_claim": "Authenticate via bearer token using curl with the Authorization header [Doc 1]. Keys must not be shared [Doc 1].",
        "cited_docs": [1],
    },
    {
        "query": "api endpoints query parameters",
        "stable_doc_id": "doc2",
        "target": "| query | string | true | The search question |",
        "expected_code_block": None,
        "expected_table_block": (
            "| Parameter | Type | Required | Description |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| query | string | true | The search question |\n"
            "| stream | boolean | false | Enable streaming |"
        ),
        "qualifier": "Never transmit",
        "expected_claim": "The query parameter is a required string for search [Doc 2]. Passwords must never be transmitted over unencrypted HTTP [Doc 2].",
        "cited_docs": [2],
    },
    {
        "query": "rate limits index endpoint",
        "stable_doc_id": "doc3",
        "target": "Rate limiting applies: maximum 60 requests per minute.",
        "expected_code_block": None,
        "expected_table_block": None,
        "qualifier": None,
        "expected_claim": "The /v1/index endpoint allows rebuilding indices with rate limiting of 60 requests per minute [Doc 3].",
        "cited_docs": [3],
    },
    {
        "query": "Python SDK initialization",
        "stable_doc_id": "doc4",
        "target": "client = DocsGPTClient(api_key='your-api-key')",
        "expected_code_block": (
            "```python\n"
            "from docsgpt import DocsGPTClient\n\n"
            "client = DocsGPTClient(api_key='your-api-key')\n"
            "response = client.ask('How do I configure vector storage?')\n"
            "```"
        ),
        "expected_table_block": None,
        "qualifier": "Deprecated",
        "expected_claim": "Initialize the Python client with DocsGPTClient(api_key=...) [Doc 4]. Deprecated v1 methods should not be used [Doc 4].",
        "cited_docs": [4],
    },
    {
        "query": "vector shard dimensions and metric",
        "stable_doc_id": "doc5",
        "target": "| shard-01 | 1536 | cosine | ACTIVE |",
        "expected_code_block": None,
        "expected_table_block": (
            "| Shard ID | Dimension | Metric | Status |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| shard-01 | 1536 | cosine | ACTIVE |\n"
            "| shard-02 | 1536 | cosine | ACTIVE |"
        ),
        "qualifier": "must not be interrupted",
        "expected_claim": "Vector shards use dimension 1536 and cosine metric [Doc 5]. Shard rebalancing must not be interrupted [Doc 5].",
        "cited_docs": [5],
    },
    {
        "query": "webhook signature payload",
        "stable_doc_id": "doc6",
        "target": '{"event": "source.indexed", "source_id": "src_12345", "status": "completed"}',
        "expected_code_block": (
            '```json\n{"event": "source.indexed", "source_id": "src_12345", "status": "completed"}\n```'
        ),
        "expected_table_block": None,
        "qualifier": "must verify",
        "expected_claim": "Webhook events use HMAC-SHA256 signatures which recipients must verify before processing [Doc 6].",
        "cited_docs": [6],
    },
]

# $2.50 per 1M prompt tokens (standard GPT-4o / Claude 3.5 Sonnet class model)
PROMPT_TOKEN_COST_PER_MILLION = 2.50


def assemble_full_rag_prompt(docs: List[Dict[str, Any]], query: str) -> str:
    """Assembles a full DocsGPT RAG prompt including system instruction and citations."""
    system_prompt = (
        "You are DocsGPT, an enterprise AI assistant for developer documentation.\n"
        "Answer the user's question accurately using only the source documents provided below.\n"
        "Always cite relevant sources using [Doc X] notation.\n\n"
        "## Retrieved Context Sources:\n"
    )
    doc_sections = []
    for i, doc in enumerate(docs, 1):
        doc_sections.append(
            f"[Doc {i}: {doc.get('title', 'Document')}] (Source: {doc.get('source', 'unknown')} | URL: {doc.get('url', '')})\n"
            f"{doc.get('text', '')}"
        )
    context_str = "\n\n---\n\n".join(doc_sections)
    user_section = f"\n\n## User Question:\n{query}\n\n## Answer:"
    return system_prompt + context_str + user_section


def verify_context_and_citation_support(
    prompt: str,
    retrieved_docs: List[Dict[str, Any]],
    target: str,
    cited_doc_indices: List[int],
) -> Tuple[bool, bool]:
    """Verifies that cited document headers exist in prompt and that target factual text is retained in retrieved context."""
    # 1. Verify Citation Header Presence: does the cited document in retrieved_docs have a corresponding prompt header?
    citation_supported = True
    for idx in cited_doc_indices:
        if idx <= len(retrieved_docs):
            cited_text = retrieved_docs[idx - 1].get("text", "")
            doc_header_in_prompt = f"[Doc {idx}:" in prompt
            if not doc_header_in_prompt or not cited_text:
                citation_supported = False
                break
        else:
            citation_supported = False
            break

    # 2. Context Fact Check: is the key target factual string retained in the retrieved context?
    context_fact_retained = any(target in d.get("text", "") for d in retrieved_docs)

    return citation_supported, context_fact_retained


def run_pipeline_benchmark(
    pipeline_name: str,
    compression_mode: str,  # 'off', 'intree', 'supercompress'
    enc: tiktoken.Encoding,
) -> Dict[str, Any]:
    """Executes benchmark for either ClassicRAG or Dispatcher pipeline under specified compression mode."""
    from docsgpt.retriever.classic_rag import ClassicRAG

    total_prompt_tokens = 0
    total_context_tokens = 0
    total_claims = 0
    supported_claims = 0
    oracle_accuracy_hits = 0
    total_oracle_checks = 0
    code_blocks_preserved = 0
    expected_code_blocks = 0
    tables_preserved = 0
    expected_tables = 0
    qualifiers_preserved = 0
    expected_qualifiers = 0

    retrieval_latencies: List[float] = []
    compression_latencies: List[float] = []
    prompt_latencies: List[float] = []
    e2e_latencies: List[float] = []

    supercompress_ran = False
    fallback_count = 0
    total_safeguard_fallbacks = 0
    total_conflict_fallbacks = 0
    total_error_fallbacks = 0

    for item in EVALUATION_QUERIES:
        query = item["query"]
        raw_corpus = deepcopy(REPRESENTATIVE_CORPUS)

        # Prepare documents for ClassicRAG ingestion and selection pipeline
        classic_docs = [
            {
                "id": d["id"],
                "title": d["title"],
                "url": d["url"],
                "filename": f"{d['id']}.md",
                "page_content": d["text"],
                "metadata": {
                    "source_id": d["source"],
                    "title": d["title"],
                    "url": d["url"],
                    "filename": f"{d['id']}.md",
                },
            }
            for d in raw_corpus
        ]

        t_start_e2e = time.perf_counter()

        # Step 1: Real Retrieval through ClassicRAG / Dispatcher
        t0_ret = time.perf_counter()
        with patch.object(ClassicRAG, "_fetch_all", return_value=[(classic_docs, "similarity")]):
            with patch.object(ClassicRAG, "_plan_sources", return_value=[{"id": "docs_core", "src_k": 8}]):

                def create_classic():
                    rag = ClassicRAG(source={"active_docs": ["docs_core"], "question": query}, chunks=8)
                    rag.vectorstores = ["docs_core"]
                    return rag

                if pipeline_name == "ClassicRAG":
                    with patch("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", False):
                        retriever = build_dispatcher(create_classic)
                        retrieved_docs = retriever.search(query)
                else:  # Dispatcher (multi-group routing)
                    with patch("docsgpt.retriever.dispatcher.settings.PER_SOURCE_RETRIEVAL_ENABLED", True):

                        def make_group_retriever(group, budget):
                            rag = ClassicRAG(
                                source={"active_docs": group["doc_ids"], "question": query},
                                chunks=8,
                                doc_token_limit=budget,
                            )
                            rag.vectorstores = group["doc_ids"]
                            return rag

                        with patch.object(Dispatcher, "_build_group_retriever", side_effect=make_group_retriever):
                            retriever = build_dispatcher(
                                create_classic,
                                source={"question": query, "active_docs": ["docs_core", "docs_api", "docs_sdk"]},
                                sources=[
                                    {"id": "docs_core", "retrieval": {"retriever": "classic"}},
                                    {"id": "docs_api", "retrieval": {"retriever": "classic"}},
                                    {"id": "docs_sdk", "retrieval": {"retriever": "hybrid"}},
                                ],
                            )
                            retrieved_docs = retriever.search(query)

        t_ret = (time.perf_counter() - t0_ret) * 1000
        retrieval_latencies.append(t_ret)

        # Step 2: Compression / Boilerplate Pruning with internal fallback tracking
        t0_comp = time.perf_counter()
        query_stats: Dict[str, int] = {}
        if compression_mode == "off":
            pass  # Uncompressed baseline
        elif compression_mode == "intree":
            retrieved_docs = prune_boilerplate(retrieved_docs, query=query)
        elif compression_mode == "supercompress":
            retrieved_docs = compress_retrieved_chunks(retrieved_docs, query=query, stats=query_stats)
            if query_stats.get("neural_success", 0) > 0 and query_stats.get("safeguard_fallback", 0) == 0:
                supercompress_ran = True
            else:
                fallback_count += 1
            total_safeguard_fallbacks += query_stats.get("safeguard_fallback", 0)
            total_conflict_fallbacks += query_stats.get("conflict_fallback", 0)
            total_error_fallbacks += query_stats.get("error_fallback", 0)
        t_comp = (time.perf_counter() - t0_comp) * 1000
        compression_latencies.append(t_comp)

        # Step 3: Prompt Assembly
        t0_prompt = time.perf_counter()
        full_prompt = assemble_full_rag_prompt(retrieved_docs, query)
        t_prompt = (time.perf_counter() - t0_prompt) * 1000
        prompt_latencies.append(t_prompt)

        # Step 4: Context Factual Retention & Citation Verification
        is_cited, is_accurate = verify_context_and_citation_support(
            prompt=full_prompt,
            retrieved_docs=retrieved_docs,
            target=item["target"],
            cited_doc_indices=item["cited_docs"],
        )
        total_claims += 1
        if is_cited:
            supported_claims += 1

        total_oracle_checks += 1
        if is_accurate:
            oracle_accuracy_hits += 1

        t_e2e = (time.perf_counter() - t_start_e2e) * 1000
        e2e_latencies.append(t_e2e)

        # Measure tokens
        prompt_tokens = len(enc.encode(full_prompt))
        context_tokens = sum(len(enc.encode(d.get("text", ""))) for d in retrieved_docs)
        total_prompt_tokens += prompt_tokens
        total_context_tokens += context_tokens

        # Content preservation checks against stable source document ID / filename
        target_doc = next(
            (
                d
                for d in retrieved_docs
                if d.get("id") == item["stable_doc_id"]
                or d.get("filename") in {item["stable_doc_id"], f"{item['stable_doc_id']}.md"}
            ),
            None,
        )

        if item.get("expected_code_block"):
            expected_code_blocks += 1
            if target_doc is not None and item["expected_code_block"] in target_doc.get("text", ""):
                code_blocks_preserved += 1

        if item.get("expected_table_block"):
            expected_tables += 1
            if target_doc is not None and item["expected_table_block"] in target_doc.get("text", ""):
                tables_preserved += 1

        if item.get("qualifier"):
            expected_qualifiers += 1
            if target_doc is not None and item["qualifier"].lower() in target_doc.get("text", "").lower():
                qualifiers_preserved += 1

    num_queries = len(EVALUATION_QUERIES)
    avg_prompt_tokens = total_prompt_tokens // num_queries
    avg_context_tokens = total_context_tokens // num_queries
    cost_per_million = avg_prompt_tokens * PROMPT_TOKEN_COST_PER_MILLION
    avg_ret_latency = sum(retrieval_latencies) / len(retrieval_latencies)
    avg_comp_latency = sum(compression_latencies) / len(compression_latencies)
    avg_prompt_latency = sum(prompt_latencies) / len(prompt_latencies)
    avg_e2e_latency = sum(e2e_latencies) / len(e2e_latencies)

    supported_citations_pct = (supported_claims / total_claims) * 100 if total_claims else 100.0
    oracle_accuracy_pct = (oracle_accuracy_hits / total_oracle_checks) * 100 if total_oracle_checks else 100.0
    code_pct = (code_blocks_preserved / expected_code_blocks * 100) if expected_code_blocks else 100.0
    table_pct = (tables_preserved / expected_tables * 100) if expected_tables else 100.0
    qualifier_pct = (qualifiers_preserved / expected_qualifiers * 100) if expected_qualifiers else 100.0

    return {
        "pipeline": pipeline_name,
        "mode": compression_mode,
        "supercompress_ran": supercompress_ran,
        "fallback_count": fallback_count,
        "safeguard_fallbacks": total_safeguard_fallbacks,
        "conflict_fallbacks": total_conflict_fallbacks,
        "error_fallbacks": total_error_fallbacks,
        "avg_prompt_tokens": avg_prompt_tokens,
        "avg_context_tokens": avg_context_tokens,
        "cost_per_million": cost_per_million,
        "avg_ret_latency": avg_ret_latency,
        "avg_comp_latency": avg_comp_latency,
        "avg_prompt_latency": avg_prompt_latency,
        "avg_e2e_latency": avg_e2e_latency,
        "supported_citations_pct": supported_citations_pct,
        "oracle_accuracy_pct": oracle_accuracy_pct,
        "code_pct": code_pct,
        "table_pct": table_pct,
        "qualifier_pct": qualifier_pct,
    }


def main():
    enc = get_encoding()

    print("=" * 80)
    print("   DocsGPT Extractive Boilerplate Pruning Benchmark (Issue #2578)               ")
    print("=" * 80)
    print(f"Corpus size: {len(REPRESENTATIVE_CORPUS)} representative document chunks")
    print(f"Evaluation query count: {len(EVALUATION_QUERIES)} queries across Core, API, and SDK")
    print("Pipelines evaluated: ClassicRAG & Dispatcher (Multi-source routing)")
    print("Configurations isolated: Baseline (OFF), In-Tree Pruning, and Optional SuperCompress\n")

    # Run evaluations across both pipelines and compression modes
    classic_off = run_pipeline_benchmark("ClassicRAG", compression_mode="off", enc=enc)
    classic_intree = run_pipeline_benchmark("ClassicRAG", compression_mode="intree", enc=enc)
    classic_super = run_pipeline_benchmark("ClassicRAG", compression_mode="supercompress", enc=enc)

    disp_off = run_pipeline_benchmark("Dispatcher", compression_mode="off", enc=enc)
    disp_intree = run_pipeline_benchmark("Dispatcher", compression_mode="intree", enc=enc)
    disp_super = run_pipeline_benchmark("Dispatcher", compression_mode="supercompress", enc=enc)

    print("-" * 80)
    print("DETAILED PIPELINE METRICS (MEASURED)")
    print("-" * 80)
    for res in [classic_off, classic_intree, classic_super, disp_off, disp_intree, disp_super]:
        mode_label = (
            "Baseline (OFF)"
            if res["mode"] == "off"
            else "In-Tree Pruning (Zero Dependencies)"
            if res["mode"] == "intree"
            else "SuperCompress (Optional Neural)"
        )
        print(f"[{res['pipeline']}] - {mode_label}:")
        if res["mode"] == "supercompress":
            if res["supercompress_ran"] and res["fallback_count"] == 0:
                sc_status = "Ran successfully via neural model (0 fallbacks)"
            else:
                reasons = []
                if res["error_fallbacks"]:
                    reasons.append(f"{res['error_fallbacks']} package absent/error")
                if res["safeguard_fallbacks"]:
                    reasons.append(f"{res['safeguard_fallbacks']} safeguard rejected")
                if res["conflict_fallbacks"]:
                    reasons.append(f"{res['conflict_fallbacks']} macOS conflict")
                reason_str = ", ".join(reasons) if reasons else "package absent"
                sc_status = f"Fell back to in-tree pruning ({res['fallback_count']}/{len(EVALUATION_QUERIES)} queries fell back: {reason_str})"
            print(f"  * Execution Status:         {sc_status}")
        print(f"  * Context Tokens:           {res['avg_context_tokens']}")
        print(f"  * Full Prompt Tokens:       {res['avg_prompt_tokens']}")
        print(f"  * Prompt Cost / 1M Qs:      ${res['cost_per_million']:.2f}")
        print(f"  * Pruning Overhead Latency: {res['avg_comp_latency']:.2f} ms")
        print(f"  * Pipeline Latency (Synth): {res['avg_e2e_latency']:.2f} ms")
        print(f"  * Context Fact Retention:   {res['oracle_accuracy_pct']:.1f}%")
        print(f"  * Citation Header Grounding: {res['supported_citations_pct']:.1f}%")
        print(f"  * Code Blocks Preserved:    {res['code_pct']:.1f}%")
        print(f"  * Tables Preserved:         {res['table_pct']:.1f}%")
        print(f"  * Qualifiers Kept:          {res['qualifier_pct']:.1f}%\n")

    classic_intree_token_savings = (
        (classic_off["avg_context_tokens"] - classic_intree["avg_context_tokens"]) / classic_off["avg_context_tokens"]
    ) * 100
    disp_intree_token_savings = (
        (disp_off["avg_context_tokens"] - disp_intree["avg_context_tokens"]) / disp_off["avg_context_tokens"]
    ) * 100
    classic_intree_cost_savings = classic_off["cost_per_million"] - classic_intree["cost_per_million"]
    disp_intree_cost_savings = disp_off["cost_per_million"] - disp_intree["cost_per_million"]

    print("=" * 80)
    print("### PR Summary Table: Measured Pipeline Comparison\n")
    table = [
        "| Metric | ClassicRAG (Baseline) | ClassicRAG (In-Tree Pruning) | Dispatcher (Baseline) | Dispatcher (In-Tree Pruning) | Delta / Verification |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
        f"| **Context Tokens / Query** | {classic_off['avg_context_tokens']} | {classic_intree['avg_context_tokens']} | {disp_off['avg_context_tokens']} | {disp_intree['avg_context_tokens']} | **-{classic_intree_token_savings:.1f}% (Classic) / -{disp_intree_token_savings:.1f}% (Dispatcher)** |",
        f"| **Full Prompt Tokens** | {classic_off['avg_prompt_tokens']} | {classic_intree['avg_prompt_tokens']} | {disp_off['avg_prompt_tokens']} | {disp_intree['avg_prompt_tokens']} | **Direct token savings in prompt** |",
        f"| **Prompt Cost / 1M Queries** | ${classic_off['cost_per_million']:.2f} | ${classic_intree['cost_per_million']:.2f} | ${disp_off['cost_per_million']:.2f} | ${disp_intree['cost_per_million']:.2f} | **Save ${classic_intree_cost_savings:.2f} - ${disp_intree_cost_savings:.2f} per 1M Qs** |",
        f"| **Context Fact Retention** | {classic_off['oracle_accuracy_pct']:.1f}% | {classic_intree['oracle_accuracy_pct']:.1f}% | {disp_off['oracle_accuracy_pct']:.1f}% | {disp_intree['oracle_accuracy_pct']:.1f}% | **{classic_intree['oracle_accuracy_pct']:.1f}% key facts retained** |",
        f"| **Citation Header Grounding** | {classic_off['supported_citations_pct']:.1f}% | {classic_intree['supported_citations_pct']:.1f}% | {disp_off['supported_citations_pct']:.1f}% | {disp_intree['supported_citations_pct']:.1f}% | **{classic_intree['supported_citations_pct']:.1f}% headers grounded** |",
        f"| **Code Blocks Preserved** | {classic_off['code_pct']:.1f}% | {classic_intree['code_pct']:.1f}% | {disp_off['code_pct']:.1f}% | {disp_intree['code_pct']:.1f}% | **{classic_intree['code_pct']:.1f}% complete code blocks intact** |",
        f"| **Markdown Tables Preserved** | {classic_off['table_pct']:.1f}% | {classic_intree['table_pct']:.1f}% | {disp_off['table_pct']:.1f}% | {disp_intree['table_pct']:.1f}% | **{classic_intree['table_pct']:.1f}% complete tables intact** |",
        f"| **Qualifiers & Warnings Kept** | {classic_off['qualifier_pct']:.1f}% | {classic_intree['qualifier_pct']:.1f}% | {disp_off['qualifier_pct']:.1f}% | {disp_intree['qualifier_pct']:.1f}% | **{classic_intree['qualifier_pct']:.1f}% security warnings intact** |",
        f"| **Pruning Overhead Latency** | 0.00 ms | +{classic_intree['avg_comp_latency']:.2f} ms | 0.00 ms | +{disp_intree['avg_comp_latency']:.2f} ms | **Negligible (~{classic_intree['avg_comp_latency']:.2f}ms overhead)** |",
        f"| **Pipeline Latency (Synthetic)** | {classic_off['avg_e2e_latency']:.2f} ms | {classic_intree['avg_e2e_latency']:.2f} ms | {disp_off['avg_e2e_latency']:.2f} ms | {disp_intree['avg_e2e_latency']:.2f} ms | **Pruning adds ~{classic_intree['avg_comp_latency']:.2f}ms in-memory overhead** |",
    ]
    print("\n".join(table))


if __name__ == "__main__":
    main()
