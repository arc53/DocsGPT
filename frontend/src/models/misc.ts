export type ActiveState = 'ACTIVE' | 'INACTIVE';

export type User = {
  avatar: string;
};

// Per-source RAG behavior contract, mirroring the backend SourceConfig
// (application/storage/db/source_config.py). All fields are optional; absent
// keys fall back to the backend defaults documented inline.
export type ChunkingStrategy =
  'classic_chunk' | 'recursive' | 'markdown' | 'parent_child' | 'semantic';

export type RetrievalExposure = 'prefetch' | 'agentic_tool';

// Ingest-time chunking knobs (bake-time; changing them requires a re-ingest).
export type SourceChunkingConfig = {
  strategy?: ChunkingStrategy; // default 'classic_chunk'
  max_tokens?: number; // default 1250
  min_tokens?: number; // default 150
  chunk_overlap?: number; // default 0
  duplicate_headers?: boolean; // default false
};

// LLM screening, a map-reduce candidate filter (off unless set).
export type SourcePrescreenConfig = {
  candidate_k?: number; // default 40, must be >= chunks
  model?: string | null; // null → reuse the request model
  batch_size?: number; // default 10
  max_keep?: number; // default 8, <= candidate_k
};

// A source's relevance: its chunks scored by the relevance model, the most
// relevant first. Never set together with `prescreen`.
export type SourceRerankerConfig = {
  type?: 'decision';
  min_relevance?: number | null; // null or 0 → reorder only; > 0 → also drop below it
  candidate_k?: number | null; // 1..100; null → 20
};

// Where the graph walk starts: matching entities, or matching relationships
// ("A streams_to B"), which can reach an entity the question never names.
export type GraphSeedStrategy = 'entities' | 'relationships';

// Query-time graph retrieval knobs (graphrag only; live, no re-ingest).
export type SourceGraphRetrievalConfig = {
  seed_strategy?: GraphSeedStrategy; // default 'entities'
  passage_nodes?: boolean; // default true
  blend_vector?: boolean; // default true
};

// Query-time retrieval knobs (live; no re-ingest needed).
export type SourceRetrievalConfig = {
  retriever?: string; // default 'classic' (only option for now)
  exposure?: RetrievalExposure; // default 'prefetch'
  chunks?: number; // top-k, default 6
  score_threshold?: number | null; // default null
  rephrase_query?: boolean; // default true
  show_links?: boolean; // default true; synced sources link each file in its service
  prescreen?: SourcePrescreenConfig | null; // null = off
  reranker?: SourceRerankerConfig | null; // null = relevance off
  graph?: SourceGraphRetrievalConfig; // graphrag retriever only
};

// Ingest-time GraphRAG extraction knobs (only used when kind === 'graphrag').
export type SourceGraphConfig = {
  extraction_model?: string | null; // null → instance default model
  max_chunks?: number | null; // null → GRAPHRAG_MAX_CHUNKS_FOR_EXTRACTION
  gleanings?: number; // extra extraction passes per chunk, default 0
};

export type SourceConfig = {
  kind?: string; // default 'classic'
  chunking?: SourceChunkingConfig;
  retrieval?: SourceRetrievalConfig;
  graph?: SourceGraphConfig;
};

export type Doc = {
  id?: string;
  name: string;
  date: string;
  model: string;
  tokens?: string;
  type?: string;
  retriever?: string;
  syncFrequency?: string;
  isNested?: boolean;
  provider?: string;
  // Per-source RAG behavior config; absent on legacy rows (treated as defaults).
  config?: SourceConfig;
  // Derived server-side from ingest_chunk_progress (sources API).
  ingestStatus?: 'processing' | 'failed';
  // Whether the current user owns this source ('user') or only has access to
  // it via a team share ('team'). Owner-only actions are gated on 'user'.
  ownership?: 'user' | 'team';
  // Access level when shared via a team: 'viewer' (read-only) or 'editor'
  // (full write). Null/absent for sources the caller owns.
  team_access?: 'viewer' | 'editor' | null;
  // The connection a synced source comes from (Google Drive account, S3 keys).
  connectionId?: string | null;
  // A Website source's hosts and page count (also older link, crawler and
  // sitemap sources); null for every other kind.
  website?: { hosts: string[]; pages: number } | null;
  // How many files the source's tree holds; null for a flat source.
  files?: number | null;
  // The caller's role and what it allows (sources API); gate UI with
  // `can(doc, action)` from utils/accessUtils.
  access?: 'owner' | 'editor' | 'viewer' | null;
  allowed_actions?: string[];
};

/**
 * A source as the app-wide knowledge list (`/api/sources`, `getDocs`) gives
 * it: the paginated listing's fields, `website` and `files` included, but
 * the folder flag named `is_nested` (see `asListedDoc`).
 */
export type KnowledgeDoc = Doc & { is_nested?: boolean };

export type GetDocsResponse = {
  docs: Doc[];
  totalDocuments: number;
  totalPages: number;
  /** The page served: the one asked for, clamped to the last. */
  currentPage: number;
  nextCursor: string;
};

export type Prompt = {
  name: string;
  id: string;
  type: string;
  // The caller's role and what it allows (prompts API); gate UI with
  // `can(prompt, action)` from utils/accessUtils. Absent on presets.
  access?: 'owner' | 'editor' | 'viewer' | null;
  allowed_actions?: string[];
  team_access?: 'viewer' | 'editor' | null;
  updated_at?: string | null;
};

export type PromptProps = {
  prompts: Prompt[];
  selectedPrompt: { name: string; id: string; type: string };
  onSelectPrompt: (name: string, id: string, type: string) => void;
  setPrompts: (prompts: { name: string; id: string; type: string }[]) => void;
};

export type DocumentsProps = {
  paginatedDocuments: Doc[] | null;
  /** Return the request's promise: the confirm stays pending on it. */
  handleDeleteDocument: (
    index: number,
    document: Doc,
  ) => void | Promise<unknown>;
};
