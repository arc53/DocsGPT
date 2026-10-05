import type { TFunction } from 'i18next';

import type { Query } from './conversationModels';

/** Values a curated error was worded from (``needed_tokens``…). */
export type ErrorParams = Record<string, unknown>;

/** A stream ``error`` event, read as ``{message, code, params}``. */
export interface StreamError {
  message: string;
  code?: string;
  params?: ErrorParams;
}

const isParams = (value: unknown): value is ErrorParams =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/**
 * The text, code and params of a stream ``error`` event. A curated error
 * carries ``code`` (``context_length_exceeded``) and, when it was worded from
 * values, ``params``; other errors carry only the text.
 */
export function readStreamError(data: {
  error?: unknown;
  code?: unknown;
  params?: unknown;
  [field: string]: unknown;
}): StreamError {
  const result: StreamError = {
    message: typeof data.error === 'string' ? data.error : '',
  };
  if (typeof data.code === 'string' && data.code) result.code = data.code;
  if (isParams(data.params)) result.params = data.params;
  return result;
}

/**
 * Sets a failed query's error code and params (Immer draft or plain object),
 * dropping those of an earlier error the new one does not carry.
 */
export function setErrorDetail(
  query: Query,
  code: string | undefined,
  params: ErrorParams | undefined,
): void {
  if (code) query.errorCode = code;
  else delete query.errorCode;
  if (params) query.errorParams = params;
  else delete query.errorParams;
}

const isCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value > 0;

/**
 * A failed turn's error in the user's language. Errors with a known code are
 * worded here, from their params when there are any; anything else (an
 * unknown code, a raw error) keeps the server's text.
 *
 * @param offersKnowledge Whether Add to Knowledge is offered under the
 *   error; the overflow wording only points at it then.
 */
export function curatedErrorText(
  t: TFunction,
  message: string,
  code?: string,
  params?: ErrorParams,
  { offersKnowledge = false }: { offersKnowledge?: boolean } = {},
): string {
  switch (code) {
    case 'context_length_exceeded': {
      const needed = params?.needed_tokens;
      const available = params?.available_tokens;
      if (isCount(needed) && isCount(available)) {
        const sizes = { needed, available };
        return offersKnowledge
          ? t('conversation.errors.contextLengthSizedKnowledge', sizes)
          : t('conversation.errors.contextLengthSized', sizes);
      }
      return offersKnowledge
        ? t('conversation.errors.contextLengthKnowledge')
        : t('conversation.errors.contextLength');
    }
    case 'server_error':
      return t('conversation.errors.serverError');
    case 'client_disconnect':
      return t('conversation.errors.clientDisconnect');
    default:
      return message;
  }
}
