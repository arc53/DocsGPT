import type { Attachment } from '../../upload/uploadSlice';

/**
 * Share of the model's context window a turn's files may take. Mirrors the
 * backend's `ATTACHMENT_BUDGET_SHARE` default; the live value comes from
 * `/api/config` (`attachment_budget_share`) and this is used until it does.
 */
export const DEFAULT_ATTACHMENT_BUDGET_SHARE = 0.5;

/** Tokens of the parsed text of the files that finished processing. */
export function attachmentTokenTotal(attachments: Attachment[]): number {
  return attachments.reduce(
    (sum, attachment) =>
      attachment.status === 'completed'
        ? sum + (attachment.token_count ?? 0)
        : sum,
    0,
  );
}

/**
 * Whether the composer's files are more than the model reads in one turn.
 * The backend then inlines what fits and leaves the rest to its attachment
 * tools (or out, for a model without tools), so this is when Knowledge
 * becomes the better home for them. An unknown window never warns.
 */
export function exceedsAttachmentBudget(
  attachments: Attachment[],
  contextWindow: number | undefined,
  share: number | undefined,
): boolean {
  if (!contextWindow || contextWindow <= 0) return false;
  const effectiveShare =
    typeof share === 'number' && Number.isFinite(share) && share > 0
      ? Math.min(share, 1)
      : DEFAULT_ATTACHMENT_BUDGET_SHARE;
  return attachmentTokenTotal(attachments) > contextWindow * effectiveShare;
}
