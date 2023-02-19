export type MESSAGE_TYPE = 'QUESTION' | 'ANSWER';

export interface Message {
  text: string;
  type: MESSAGE_TYPE;
}

export interface ConversationState {
  conversation: Message[];
}
