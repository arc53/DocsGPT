import type { Query } from './conversationModels';

/** How a retry or an edit of an existing turn goes out. */
export interface ResendPlan {
  /** The attachment ids the request carries. */
  attachmentIds: string[];
  /** Whether the row keeps its Idempotency-Key for server-side dedup. */
  keepIdempotencyKey: boolean;
  /** Whether the row's file chips go, because the request has no files. */
  dropRowAttachments: boolean;
}

/**
 * Decide what a retry or an edit of ``row`` sends.
 *
 * The composer was emptied by the original send, so the row's own ids go
 * again; but once its files were turned into Knowledge they are asked
 * through the selected Knowledge instead, and sending them again would only
 * overflow the same way. Without them it is a different request, so the
 * first one's key must not answer it.
 *
 * Args:
 *   row: The turn being re-sent.
 *   isRetry: A retry (same prompt) rather than an edit.
 *
 * Returns:
 *   The ids to send, whether to keep the key and whether to drop the chips.
 */
export function resendPlan(
  row: Query | undefined,
  isRetry: boolean,
): ResendPlan {
  if (row?.attachmentsInKnowledge) {
    return {
      attachmentIds: [],
      keepIdempotencyKey: false,
      dropRowAttachments: true,
    };
  }
  return {
    attachmentIds: (row?.attachments ?? []).map((a) => a.id),
    keepIdempotencyKey: isRetry,
    dropRowAttachments: false,
  };
}

/** Where a question typed into the composer goes. */
export type ComposerSubmitTarget =
  { kind: 'new' } | { kind: 'retry'; index: number; samePrompt: boolean };

/**
 * Decide whether a composer send starts a new turn or retries the last one.
 *
 * After a failed turn the next question replaces it. Not when the composer
 * holds files of its own: retrying would re-send the failed row's files
 * (the same overflow again) and leave the new ones neither sent nor cleared,
 * so those start a new turn.
 *
 * Args:
 *   options.question: The question typed.
 *   options.queries: The conversation's turns.
 *   options.lastQueryReturnedErr: Whether the last turn failed.
 *   options.composerFileCount: Files ready to send from the composer.
 *
 * Returns:
 *   A new turn, or the index of the failed turn and whether the prompt is
 *   unchanged.
 */
export function composerSubmitTarget(options: {
  question: string;
  queries: Query[];
  lastQueryReturnedErr: boolean;
  composerFileCount: number;
}): ComposerSubmitTarget {
  const { question, queries, lastQueryReturnedErr, composerFileCount } =
    options;
  if (!lastQueryReturnedErr || queries.length === 0 || composerFileCount > 0) {
    return { kind: 'new' };
  }
  const index = queries.length - 1;
  return {
    kind: 'retry',
    index,
    samePrompt: queries[index].prompt === question,
  };
}
