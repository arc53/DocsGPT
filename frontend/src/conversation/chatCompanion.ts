import { createContext, useContext } from 'react';

/** One retrieved source of an answer, as the answer's sources list shows it. */
export type AnswerSource = {
  title: string;
  text: string;
  link?: string;
  connector_key?: string | null;
  connector_name?: string | null;
};

/**
 * The chat's one docked side panel slot (DESIGN.md "Side panels"): an answer
 * opens its sources there, beside the chat, replacing an open artifact.
 * Without a provider (a shared chat, an agent preview) the answer opens its
 * sources in a modal SidePanel instead.
 */
export const ChatCompanionContext = createContext<{
  openSources: (sources: AnswerSource[]) => void;
} | null>(null);

export const useChatCompanion = () => useContext(ChatCompanionContext);
