export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER' | 'ERROR';
export type Status = 'idle' | 'loading' | 'failed';

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface ConversationState {
  conversation: Message[];
  status: Status;
}

export interface Answer {
  answer: string;
  query: string;
  result: string;
}
