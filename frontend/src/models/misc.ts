export type ActiveState = 'ACTIVE' | 'INACTIVE';

export type User = {
  avatar: string;
};
export type Doc = {
  location: string;
  name: string;
  language: string;
  version: string;
  description: string;
  fullName: string;
  date: string;
  docLink: string;
  model: string;
};

export type PromptProps = {
  prompts: { name: string; id: string; type: string }[];
  selectedPrompt: { name: string; id: string; type: string };
  onSelectPrompt: (name: string, id: string, type: string) => void;
  setPrompts: (prompts: { name: string; id: string; type: string }[]) => void;
  apiHost: string;
};

export type DocumentsProps = {
  documents: Doc[] | null;
  handleDeleteDocument: (index: number, document: Doc) => void;
};

export type CreateAPIKeyModalProps = {
  close: () => void;
  createAPIKey: (payload: { name: string; source: string }) => void;
};

export type SaveAPIKeyModalProps = {
  apiKey: string;
  close: () => void;
};
