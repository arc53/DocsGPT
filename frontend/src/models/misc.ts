export type ActiveState = 'ACTIVE' | 'INACTIVE';

export type User = {
  avatar: string;
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
