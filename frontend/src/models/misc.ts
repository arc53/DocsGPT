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

export type CreateAPIKeyModalProps = {
  close: () => void;
  createAPIKey: (payload: {
    name: string;
    source: string;
    prompt_id: string;
    chunks: string;
  }) => void;
};

export type SaveAPIKeyModalProps = {
  apiKey: string;
  close: () => void;
};
