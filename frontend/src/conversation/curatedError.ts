import i18next, { type TFunction } from 'i18next';

import { isRecord } from '../utils/wireGuards';
import { CUSTOM_MODEL_CHAT_PERSONAL_ONLY_KEY } from '../models/customModelErrors';
import type { Query } from './conversationModels';
import {
  AGENT_LIMIT_EXCEEDED,
  type AgentLimitErrorBody,
  agentLimitErrorMessage,
  QUOTA_EXCEEDED,
  type QuotaErrorBody,
  quotaErrorMessage,
} from './quotaError';

/**
 * The code of the error the client writes itself when a stream ends without
 * a terminal frame: the connection dropped, so the server may or may not
 * have taken the request.
 */
export const CONNECTION_LOST = 'connection_lost';

/** Values a curated error was worded from (``needed_tokens``…). */
export type ErrorParams = Record<string, unknown>;

/** A stream ``error`` event, read as ``{message, code, params}``. */
export interface StreamError {
  message: string;
  code?: string;
  params?: ErrorParams;
}

const isParams = (value: unknown): value is ErrorParams => isRecord(value);

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

const isNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

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
    case 'time_limit':
      return t('conversation.errors.timeLimit');
    case 'stopped':
      return t('conversation.errors.stopped');
    case 'no_answer':
      return t('conversation.errors.noAnswer');
    // The chat's agent lives in another workspace; the bubble offers the
    // switch when the caller is in that workspace.
    case 'workspace_mismatch':
      return t('workspace.chat.mismatch');
    case 'workspace_not_found':
      return t('workspace.chat.notFound');
    // The person's allowance, before the run or during it (the partial
    // answer stays above): worded from its values, with the reset.
    case QUOTA_EXCEEDED:
      return isNumber(params?.usage) && isNumber(params?.limit)
        ? quotaErrorMessage(params as QuotaErrorBody, t, i18next.language)
        : t('conversation.quotaExceeded.reached');
    // The agent's own limit; a refusal before the run arrives worded.
    case AGENT_LIMIT_EXCEEDED:
      return isNumber(params?.usage) && isNumber(params?.limit)
        ? agentLimitErrorMessage(
            params as AgentLimitErrorBody,
            t,
            i18next.language,
          )
        : message;
    // Someone else pays for this agent and can't: never their numbers.
    case 'agent_paused':
      return t('payer.notice.chat.agentPaused');
    case 'no_payer':
      return t('payer.notice.chat.noPayer');
    // A team chat asked for the caller's own custom model.
    case 'custom_model_personal_only':
      return t(CUSTOM_MODEL_CHAT_PERSONAL_ONLY_KEY);
    default:
      return message;
  }
}
