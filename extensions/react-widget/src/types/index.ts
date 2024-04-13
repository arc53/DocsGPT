export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE';

export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string }[];
  conversationId?: string | null;
  title?: string | null;
}