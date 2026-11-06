/**
 * The prompt recipe's proposals and the pure helpers its review uses: which
 * mode the drawer runs in, reading a proposal off the stream, applying the
 * accepted edits and splitting the text into the diff the review shows.
 */

/** One server-checked change: `find` occurs once in the text it was made for. */
export type PromptEdit = {
  id: string;
  find: string;
  replace: string;
  reason: string;
};

/** What a change does to the prompt that the user should know (server codes). */
export type PromptCheck =
  'to_template' | 'to_persona' | 'boundaries_removed' | 'citations_removed';

export const PROMPT_CHECKS: PromptCheck[] = [
  'to_template',
  'to_persona',
  'boundaries_removed',
  'citations_removed',
];

export type PromptImproveProposal = {
  mode: 'improve';
  message: string;
  edits: PromptEdit[];
  result: string;
  templateMode: { before: boolean; after: boolean };
  warnings: string[];
  checks: PromptCheck[];
  /** Next changes the model offers, each worded as the user's request. */
  suggestions: string[];
};

export type PromptWriteProposal = {
  mode: 'write';
  message: string;
  name: string;
  content: string;
  reason: string;
  warnings: string[];
  checks: PromptCheck[];
  /** Guesses the model made that the user should check. */
  assumptions: string[];
  suggestions: string[];
};

export type PromptProposal = PromptImproveProposal | PromptWriteProposal;

/**
 * `improve` for a prompt with text, `write` for an empty one, saved or new
 * (the server has nothing to improve in an empty prompt).
 */
export function promptDrafterMode(content: string): 'improve' | 'write' {
  return content.trim() ? 'improve' : 'write';
}

const isString = (value: unknown): value is string => typeof value === 'string';

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(isString) : [];
}

function checks(value: unknown): PromptCheck[] {
  return strings(value).filter((code): code is PromptCheck =>
    PROMPT_CHECKS.includes(code as PromptCheck),
  );
}

/**
 * A `proposal` event's payload as a prompt proposal.
 *
 * Args:
 *   raw: The payload.
 *
 * Returns:
 *   The proposal, or null when it isn't one.
 */
/** A proposal's `edits`, malformed ones dropped. */
export function readPromptEdits(raw: unknown): PromptEdit[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter(
      (edit): edit is PromptEdit =>
        !!edit &&
        typeof edit === 'object' &&
        isString((edit as PromptEdit).id) &&
        isString((edit as PromptEdit).find) &&
        isString((edit as PromptEdit).replace),
    )
    .map(({ id, find, replace, reason }) => ({
      id,
      find,
      replace,
      reason: isString(reason) ? reason : '',
    }));
}

/** A proposal's `checks`, unknown codes dropped. */
export const readPromptChecks = (raw: unknown): PromptCheck[] => checks(raw);

export function readPromptProposal(raw: unknown): PromptProposal | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const message = isString(value.message) ? value.message : '';
  if (value.mode === 'improve' && Array.isArray(value.edits)) {
    const mode = (value.template_mode ?? {}) as Record<string, unknown>;
    return {
      mode: 'improve',
      message,
      edits: readPromptEdits(value.edits),
      result: isString(value.result) ? value.result : '',
      templateMode: {
        before: mode.before === true,
        after: mode.after === true,
      },
      warnings: strings(value.warnings),
      checks: checks(value.checks),
      suggestions: strings(value.suggestions),
    };
  }
  if (
    value.mode === 'write' &&
    isString(value.name) &&
    isString(value.content)
  ) {
    return {
      mode: 'write',
      message,
      name: value.name,
      content: value.content,
      reason: isString(value.reason) ? value.reason : '',
      warnings: strings(value.warnings),
      checks: checks(value.checks),
      assumptions: strings(value.assumptions),
      suggestions: strings(value.suggestions),
    };
  }
  return null;
}

type Located = { edit: PromptEdit; start: number; end: number };

/** Each edit's place in `content`, in text order; an edit whose text is gone is left out. */
function locate(content: string, edits: PromptEdit[]): Located[] {
  return edits
    .map((edit) => {
      const start = content.indexOf(edit.find);
      return { edit, start, end: start + edit.find.length };
    })
    .filter((item) => item.start >= 0)
    .sort((a, b) => a.start - b.start);
}

/**
 * The edits that still fit `content`: each one's text occurs there exactly
 * once and overlaps no edit kept before it. The server checked them against
 * the copy the model read; the saved text can differ (a long prompt is
 * read cut short).
 *
 * Args:
 *   content: The text the review will run on.
 *   edits: The proposal's edits.
 *
 * Returns:
 *   The edits to review, in their order.
 */
export function fittingEdits(
  content: string,
  edits: PromptEdit[],
): PromptEdit[] {
  const taken: [number, number][] = [];
  return edits.filter((edit) => {
    const start = content.indexOf(edit.find);
    if (!edit.find || start < 0 || content.indexOf(edit.find, start + 1) >= 0)
      return false;
    const end = start + edit.find.length;
    if (taken.some(([from, to]) => start < to && from < end)) return false;
    taken.push([start, end]);
    return true;
  });
}

/**
 * The text with the accepted edits applied; the others leave their passage as
 * it was.
 *
 * Args:
 *   content: The text the edits were made for.
 *   edits: The proposal's edits.
 *   accepted: Whether an edit (by id) is applied.
 *
 * Returns:
 *   The new text.
 */
export function applyPromptEdits(
  content: string,
  edits: PromptEdit[],
  accepted: (id: string) => boolean,
): string {
  let out = '';
  let cursor = 0;
  for (const { edit, start, end } of locate(content, edits)) {
    if (start < cursor) continue;
    out += content.slice(cursor, start);
    out += accepted(edit.id) ? edit.replace : edit.find;
    cursor = end;
  }
  return out + content.slice(cursor);
}

export type PromptDiffSegment =
  | { kind: 'text'; text: string }
  | { kind: 'change'; edit: PromptEdit; number: number };

/**
 * The text cut into unchanged runs and changes, each change numbered in text
 * order (the number the review's list uses).
 *
 * Args:
 *   content: The text the edits were made for.
 *   edits: The proposal's edits.
 *
 * Returns:
 *   The segments, in order.
 */
export function promptDiffSegments(
  content: string,
  edits: PromptEdit[],
): PromptDiffSegment[] {
  const segments: PromptDiffSegment[] = [];
  let cursor = 0;
  let number = 0;
  for (const { edit, start, end } of locate(content, edits)) {
    if (start < cursor) continue;
    if (start > cursor)
      segments.push({ kind: 'text', text: content.slice(cursor, start) });
    number += 1;
    segments.push({ kind: 'change', edit, number });
    cursor = end;
  }
  if (cursor < content.length)
    segments.push({ kind: 'text', text: content.slice(cursor) });
  return segments;
}
