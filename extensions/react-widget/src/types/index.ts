export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';
export type FEEDBACK = 'LIKE' | 'DISLIKE';
export type THEME = 'light' | 'dark';
export interface Query {
  prompt: string;
  response?: string;
  feedback?: FEEDBACK;
  error?: string;
  sources?: { title: string; text: string }[];
  conversationId?: string | null;
  title?: string | null;
}
export interface WidgetProps {
  apiHost?: string;
  apiKey?: string;
  avatar?: string;
  title?: string;
  description?: string;
  heroTitle?: string;
  heroDescription?: string;
  size?: 'small' | 'medium' | 'large';
  theme?:THEME,
  buttonIcon?:string;
  buttonBg?:string;
  collectFeedback?:boolean
}