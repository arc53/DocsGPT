import type { Dispatch } from '@reduxjs/toolkit';

import userService from '../api/services/userService';
import type { Prompt } from '../models/misc';
import type { RootState } from '../store';
import { setPrompt } from './preferenceSlice';

/** The prompt chats use until the user picks another. */
export const DEFAULT_CHAT_PROMPT: Prompt = {
  id: 'default',
  name: 'default',
  type: 'public',
};

/**
 * Where this browser kept the chat prompt before the server did. Read once
 * to move the choice to the server, then removed.
 */
export const LEGACY_PROMPT_KEY = 'DocsGPTPrompt';

/** The fields the chat prompt keeps; a listed row also carries usage. */
const asChatPrompt = ({ id, name, type }: Prompt): Prompt => ({
  id,
  name,
  type,
});

function readLegacyPrompt(): Prompt | null {
  try {
    const raw = localStorage.getItem(LEGACY_PROMPT_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed.id === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

function forgetLegacyPrompt(): void {
  try {
    localStorage.removeItem(LEGACY_PROMPT_KEY);
  } catch {
    // Storage blocked: nothing was kept there either.
  }
}

/**
 * The prompt the user's chats use, as the server stores it.
 *
 * Args:
 *   token: The session token, or null on an instance without auth.
 *
 * Returns:
 *   A preset name or a prompt id; null when the server didn't answer.
 */
export async function fetchChatPromptId(
  token: string | null,
): Promise<string | null> {
  try {
    const response = await userService.getPreferences(token);
    if (!response.ok) return null;
    const data = await response.json();
    return typeof data?.chat_prompt_id === 'string'
      ? data.chat_prompt_id
      : null;
  } catch {
    return null;
  }
}

async function saveChatPromptId(
  id: string,
  token: string | null,
): Promise<boolean> {
  try {
    const response = await userService.updatePreferences(
      { chat_prompt_id: id },
      token,
    );
    return Boolean(response?.ok);
  } catch {
    return false;
  }
}

/**
 * Sets the chat prompt at start from the server's answer and the prompt list.
 *
 * A prompt this browser picked before the server kept the choice moves to
 * the server once: when the server still says `default` and that prompt is
 * listed, it is saved there and the browser's copy removed (kept for the
 * next start if the save fails). With no server answer (signed out, an
 * unreachable server) the browser's copy is used while it is listed, else
 * `default`, and nothing is sent.
 *
 * Args:
 *   serverId: The server's `chat_prompt_id`, or null when there was none.
 *   prompts: The prompts the user can pick from.
 *   token: The session token.
 */
export const loadChatPrompt =
  (serverId: string | null, prompts: Prompt[], token: string | null) =>
  async (dispatch: Dispatch): Promise<void> => {
    const legacy = readLegacyPrompt();
    const listed = (id: string) => prompts.find((prompt) => prompt.id === id);
    const legacyListed = legacy ? listed(legacy.id) : undefined;

    if (serverId === null) {
      dispatch(
        setPrompt(
          legacyListed ? asChatPrompt(legacyListed) : DEFAULT_CHAT_PROMPT,
        ),
      );
      return;
    }
    if (
      serverId === DEFAULT_CHAT_PROMPT.id &&
      legacyListed &&
      legacyListed.id !== serverId
    ) {
      dispatch(setPrompt(asChatPrompt(legacyListed)));
      if (await saveChatPromptId(legacyListed.id, token)) forgetLegacyPrompt();
      return;
    }
    // Without the list there is no telling whether the old choice still
    // exists; it waits for the next start.
    if (prompts.length > 0) forgetLegacyPrompt();
    const chosen = listed(serverId);
    dispatch(
      setPrompt(
        chosen
          ? asChatPrompt(chosen)
          : // The list didn't load: keep the id; a later list names it.
            { id: serverId, name: serverId, type: 'private' },
      ),
    );
  };

/**
 * Makes `prompt` the chat prompt: it switches at once and switches back
 * when the server refuses (the caller reports that).
 *
 * Args:
 *   prompt: The prompt to use in chats.
 *   token: The session token.
 *
 * Returns:
 *   Whether the server saved it.
 */
export const chooseChatPrompt =
  (prompt: Prompt, token: string | null) =>
  async (
    dispatch: Dispatch,
    getState: () => Pick<RootState, 'preference'>,
  ): Promise<boolean> => {
    const previous = getState().preference.prompt;
    if (previous.id === prompt.id) return true;
    dispatch(setPrompt(asChatPrompt(prompt)));
    if (await saveChatPromptId(prompt.id, token)) return true;
    // A later pick that is still saving keeps its place.
    if (getState().preference.prompt.id === prompt.id)
      dispatch(setPrompt(previous));
    return false;
  };
