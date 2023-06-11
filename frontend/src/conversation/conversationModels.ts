export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE';

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface ConversationState {
  queries: Query[];
  status: Status;
}

export interface Answer {
  answer: string;
  query: string;
  result: string;
  sources: { title: string; text: string }[];
}

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string }[];
}
