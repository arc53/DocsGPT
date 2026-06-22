export type ActiveState = 'ACTIVE' | 'INACTIVE';

export type User = {
  avatar: string;
};

// Per-source RAG behavior contract, mirroring the backend SourceConfig
// (application/storage/db/source_config.py). All fields are optional; absent
// keys fall back to the backend defaults documented inline.
export type ChunkingStrategy =
  | 'classic_chunk'
  | 'recursive'
  | 'markdown'
  | 'parent_child'
  | 'semantic';

export type RetrievalExposure = 'prefetch' | 'agentic_tool';

// Ingest-time chunking knobs (bake-time; changing them requires a re-ingest).
export type SourceChunkingConfig = {
  strategy?: ChunkingStrategy; // default 'classic_chunk'
  max_tokens?: number; // default 1250
  min_tokens?: number; // default 150
  duplicate_headers?: boolean; // default false
};

// Map-reduce candidate-filter config (off unless set).
export type SourcePrescreenConfig = {
  candidate_k?: number; // default 40, must be >= chunks
  model?: string | null; // null → reuse the request model
  batch_size?: number; // default 10
  max_keep?: number; // default 8, <= candidate_k
};

// Query-time retrieval knobs (live; no re-ingest needed).
export type SourceRetrievalConfig = {
  retriever?: string; // default 'classic' (only option for now)
  exposure?: RetrievalExposure; // default 'prefetch'
  chunks?: number; // top-k, default 2
  score_threshold?: number | null; // default null
  rephrase_query?: boolean; // default true
  prescreen?: SourcePrescreenConfig | null; // null = off
};

export type SourceConfig = {
  kind?: string; // default 'classic'
  chunking?: SourceChunkingConfig;
  retrieval?: SourceRetrievalConfig;
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
};

export type GetDocsResponse = {
  docs: Doc[];
  totalDocuments: number;
  totalPages: number;
  nextCursor: string;
};

export type Prompt = {
  name: string;
  id: string;
  type: string;
};

export type PromptProps = {
  prompts: { name: string; id: string; type: string }[];
  selectedPrompt: { name: string; id: string; type: string };
  onSelectPrompt: (name: string, id: string, type: string) => void;
  setPrompts: (prompts: { name: string; id: string; type: string }[]) => void;
};

export type DocumentsProps = {
  paginatedDocuments: Doc[] | null;
  handleDeleteDocument: (index: number, document: Doc) => void;
};
