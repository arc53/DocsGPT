import type { Dispatch } from '@reduxjs/toolkit';

import userService from '../api/services/userService';
import type { Prompt } from '../models/misc';
import type { RootState } from '../store';
import { getPrompts } from './preferenceApi';
import { setPrompt, setPrompts } from './preferenceSlice';

type GetState = () => Pick<RootState, 'preference'>;

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
 * How long start-up waits before asking for the chat prompt again after the
 * server couldn't answer, per retry.
 */
export const CHAT_PROMPT_RETRY_MS = [2_000, 8_000];

/**
 * The prompt the user's chats use, as the server stores it.
 *
 * Args:
 *   token: The session token, or null on an instance without auth.
 *   retryDelays: Waits before each retry when the server is unreachable or
 *     fails (5xx); a refusal is final.
 *   cancelled: Stops the retries (the session it was for has ended).
 *
 * Returns:
 *   A preset name or a prompt id; null when the server didn't answer.
 */
export async function fetchChatPromptId(
  token: string | null,
  retryDelays: readonly number[] = [],
  cancelled: () => boolean = () => false,
): Promise<string | null> {
  for (let attempt = 0; ; attempt += 1) {
    let retry = true;
    try {
      const response = await userService.getPreferences(token);
      if (response.ok) {
        const data = await response.json();
        return typeof data?.chat_prompt_id === 'string'
          ? data.chat_prompt_id
          : null;
      }
      retry = response.status >= 500;
    } catch {
      // Unreachable: worth asking again.
    }
    const delay = retryDelays[attempt];
    if (!retry || delay === undefined || cancelled()) return null;
    await new Promise((done) => setTimeout(done, delay));
    if (cancelled()) return null;
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
 * A save waiting to be sent, and its caller waiting for the outcome. `user`:
 * the user's pick; otherwise the move of an old browser choice, which
 * doesn't switch back when it fails and reports only its own save.
 */
type PendingPick = {
  prompt: Prompt;
  user: boolean;
  resolve: (saved: boolean) => void;
};

/**
 * One store's chat-prompt saves for one token: what the server last
 * confirmed, the pick waiting to be sent, and whether one is in flight.
 */
type ChatPromptSession = {
  token: string | null;
  /** The last value the server confirmed (loaded or saved); null unknown. */
  confirmed: Prompt | null;
  /** What chats showed before the first pick, while nothing is confirmed. */
  shownBefore: Prompt | null;
  /** The user picked in this session. */
  picked: boolean;
  /** One of the user's picks was saved. */
  pickSaved: boolean;
  next: PendingPick | null;
  saving: boolean;
  timer: ReturnType<typeof setTimeout> | undefined;
};

// Keyed by the store's getState, so each store (and test) has its own.
const sessions = new WeakMap<GetState, ChatPromptSession>();

function sessionOf(
  getState: GetState,
  token: string | null,
): ChatPromptSession {
  const current = sessions.get(getState);
  if (current && current.token === token) return current;
  // A new token is a new user or sign-in: nothing carries over. A pick
  // still waiting is dropped, and its caller hears it wasn't saved.
  if (current?.timer) clearTimeout(current.timer);
  if (current?.next) {
    current.next.resolve(false);
    current.next = null;
  }
  const fresh: ChatPromptSession = {
    token,
    confirmed: null,
    shownBefore: null,
    picked: false,
    pickSaved: false,
    next: null,
    saving: false,
    timer: undefined,
  };
  sessions.set(getState, fresh);
  return fresh;
}

/**
 * Whether the user's pick decides the chat prompt: it is waiting or saving,
 * or one was saved. Start-up then leaves the prompt alone; after picks that
 * all failed it sets the server's again.
 */
const pickStands = (session: ChatPromptSession): boolean =>
  session.picked &&
  (session.pickSaved || session.saving || session.next !== null);

/**
 * The prompt for an id: the listed one, else a stand-in a later list names.
 */
function promptFor(id: string, prompts: Prompt[]): Prompt {
  const listed = prompts.find((prompt) => prompt.id === id);
  return listed
    ? asChatPrompt(listed)
    : {
        id,
        name: id,
        type: id === DEFAULT_CHAT_PROMPT.id ? 'public' : 'private',
      };
}

/**
 * Sets the chat prompt at start from the server's answer and the prompt list.
 *
 * A prompt this browser picked before the server kept the choice moves to
 * the server once: when the server still says `default` and that prompt is
 * listed, it is saved there and the browser's copy removed (kept for the
 * next start if the save fails). With no server answer (signed out, an
 * unreachable server) the browser's copy is used while it is listed, else
 * `default`, and nothing is sent. A pick the user made meanwhile stays.
 *
 * Args:
 *   serverId: The server's `chat_prompt_id`, or null when there was none.
 *   prompts: The prompts the user can pick from.
 *   token: The session token.
 */
export const loadChatPrompt =
  (serverId: string | null, prompts: Prompt[], token: string | null) =>
  async (dispatch: Dispatch, getState: GetState): Promise<void> => {
    const session = sessionOf(getState, token);
    if (serverId !== null && !session.confirmed)
      session.confirmed = promptFor(serverId, prompts);
    if (pickStands(session)) return;
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
      // Through the save queue, so a pick made meanwhile goes after it.
      const moved = queueSave(
        session,
        { prompt: asChatPrompt(legacyListed), user: false },
        dispatch,
        getState,
        0,
      );
      if (await moved) forgetLegacyPrompt();
      return;
    }
    // Without the list there is no telling whether the old choice still
    // exists; it waits for the next start.
    if (prompts.length > 0) forgetLegacyPrompt();
    // The list didn't load: keep the id; a later list names it.
    dispatch(setPrompt(promptFor(serverId, prompts)));
  };

/**
 * Shows the server's chat prompt as soon as it is known, before the prompt
 * list: a chat started meanwhile uses it. Skipped when the user picked
 * already, or when a prompt this browser kept may still move to the server
 * (`loadChatPrompt` decides that with the list).
 */
const showServerChatPrompt =
  (serverId: string, token: string | null) =>
  (dispatch: Dispatch, getState: GetState): void => {
    const session = sessionOf(getState, token);
    if (pickStands(session)) return;
    if (serverId === DEFAULT_CHAT_PROMPT.id && readLegacyPrompt()) return;
    dispatch(setPrompt(promptFor(serverId, getState().preference.prompts)));
  };

/**
 * Loads the prompt list and the chat prompt at start. The server's chat
 * prompt applies as soon as it answers; the list then names it, and
 * `loadChatPrompt` settles it (and moves an old browser choice) once both
 * are in.
 *
 * Args:
 *   token: The session token.
 *   options.signedOut: A mode that needs a token has none yet: the server
 *     is asked nothing about the user, and default stays.
 *   options.cancelled: The load is for a session that has ended.
 */
export const initChatPrompt =
  (
    token: string | null,
    { signedOut, cancelled }: { signedOut: boolean; cancelled: () => boolean },
  ) =>
  async (
    dispatch: (action: unknown) => unknown,
    getState: GetState,
  ): Promise<void> => {
    const list = getPrompts(token).then((prompts) => {
      if (!cancelled()) dispatch(setPrompts(prompts));
      return prompts;
    });
    const serverId = signedOut
      ? Promise.resolve(null)
      : fetchChatPromptId(token, CHAT_PROMPT_RETRY_MS, cancelled).then((id) => {
          if (id !== null && !cancelled())
            showServerChatPrompt(id, token)(dispatch as Dispatch, getState);
          return id;
        });
    const [prompts, id] = await Promise.all([list, serverId]);
    if (cancelled()) return;
    await loadChatPrompt(id, prompts, token)(dispatch as Dispatch, getState);
  };

/**
 * Sends the waiting picks one at a time, so answers can't land out of
 * order. Only the newest waiting pick is sent; one the server already
 * holds is not sent again. When the last pick fails with none behind it,
 * chats switch back to what the server last confirmed (or, with nothing
 * confirmed, to what they showed before the first pick).
 */
async function drainPicks(
  session: ChatPromptSession,
  dispatch: Dispatch,
  getState: GetState,
): Promise<void> {
  session.saving = true;
  while (session.next && !session.timer) {
    const { prompt, user, resolve } = session.next;
    session.next = null;
    const saved =
      session.confirmed?.id === prompt.id ||
      (await saveChatPromptId(prompt.id, session.token));
    if (saved) {
      session.confirmed = asChatPrompt(prompt);
      if (user) session.pickSaved = true;
    }
    const superseded = session.next !== null;
    if (
      user &&
      !saved &&
      !superseded &&
      getState().preference.prompt.id === prompt.id
    )
      dispatch(
        setPrompt(
          session.confirmed ?? session.shownBefore ?? DEFAULT_CHAT_PROMPT,
        ),
      );
    // A failed pick with a newer one behind it has nothing to report.
    resolve(saved || (user && superseded));
  }
  session.saving = false;
}

/**
 * Puts a save in the queue, replacing the one waiting (whose caller hears
 * it was replaced), and starts sending now or after `delayMs`.
 *
 * Returns:
 *   The save's outcome, as `drainPicks` reports it.
 */
function queueSave(
  session: ChatPromptSession,
  pick: Omit<PendingPick, 'resolve'>,
  dispatch: Dispatch,
  getState: GetState,
  delayMs: number,
): Promise<boolean> {
  // Replaced before it was sent: a user pick has nothing to report; the
  // move of an old choice wasn't saved.
  session.next?.resolve(session.next.user);
  const outcome = new Promise<boolean>((resolve) => {
    session.next = { ...pick, resolve };
  });
  if (session.timer) clearTimeout(session.timer);
  session.timer = undefined;
  if (delayMs > 0)
    session.timer = setTimeout(() => {
      session.timer = undefined;
      if (!session.saving) void drainPicks(session, dispatch, getState);
    }, delayMs);
  else if (!session.saving) void drainPicks(session, dispatch, getState);
  return outcome;
}

/**
 * The prompt `deletedId` was deleted. The server reads a deleted chat
 * prompt back as default, so default becomes the confirmed value (what a
 * failed pick switches back to), and chats showing it switch to default.
 *
 * Args:
 *   deletedId: The deleted prompt's id.
 *   token: The session token.
 */
export const chatPromptDeleted =
  (deletedId: string, token: string | null) =>
  (dispatch: Dispatch, getState: GetState): void => {
    const session = sessionOf(getState, token);
    if (session.confirmed?.id === deletedId)
      session.confirmed = DEFAULT_CHAT_PROMPT;
    if (session.shownBefore?.id === deletedId)
      session.shownBefore = DEFAULT_CHAT_PROMPT;
    if (getState().preference.prompt.id === deletedId)
      dispatch(setPrompt(DEFAULT_CHAT_PROMPT));
  };

/**
 * Makes `prompt` the chat prompt: it switches at once and switches back
 * when the server refuses (the caller reports that). Saves go one at a time
 * and the latest pick wins.
 *
 * Args:
 *   prompt: The prompt to use in chats.
 *   token: The session token.
 *   delayMs: Wait this long for a newer pick before saving (arrow keys over
 *     the radios); 0 saves at once.
 *
 * Returns:
 *   Whether the server saved it; true for a pick a newer one replaced,
 *   false for one dropped because the session (token) changed.
 */
export const chooseChatPrompt =
  (prompt: Prompt, token: string | null, delayMs = 0) =>
  (dispatch: Dispatch, getState: GetState): Promise<boolean> => {
    const session = sessionOf(getState, token);
    if (!session.picked) {
      session.picked = true;
      session.shownBefore = getState().preference.prompt;
    }
    if (getState().preference.prompt.id !== prompt.id)
      dispatch(setPrompt(asChatPrompt(prompt)));
    return queueSave(
      session,
      { prompt: asChatPrompt(prompt), user: true },
      dispatch,
      getState,
      delayMs,
    );
  };
