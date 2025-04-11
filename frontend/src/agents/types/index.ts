export type Agent = {
  id?: string;
  name: string;
  description: string;
  image: string;
  source: string;
  chunks: string;
  retriever: string;
  prompt_id: string;
  tools: string[];
  agent_type: string;
  status: string;
  key?: string;
};
