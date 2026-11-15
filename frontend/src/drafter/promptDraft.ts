/**
 * The prompt recipe's proposals (improve, review and write) and the pure
 * helpers its review uses: which mode the drawer runs in, reading a
 * proposal off the stream, applying the accepted edits and splitting the
 * text into the diff the review shows.
 */
import { asRecord, isString } from '../utils/wireGuards';

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
  /** The review applies them to the text itself. */
  edits: PromptEdit[];
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

/** The review's checklist, in its order (the server's check codes). */
export const REVIEW_CHECKS = [
  'audience',
  'scope',
  'hand_off',
  'unknowns',
  'tone',
  'placeholders',
  'builtin_rules',
  'builtin_lines',
  'agents_fit',
] as const;

export type ReviewCheck = (typeof REVIEW_CHECKS)[number];

/**
 * One thing a review found. The model's carry their own `title` and
 * `detail`; the server's own checks (`source: "server"`) come with `code`
 * and `text` only, and the client words them.
 */
export type ReviewFinding = {
  id: string;
  check: string;
  /** `fix` goes under To fix, `look` under Worth a look. */
  severity: 'fix' | 'look';
  title: string;
  detail: string;
  /** The id of the proposal's edit that makes the fix. */
  edit: string | null;
  /** A detail the fix needs from the user: the ask bar's prefill. */
  ask: { label: string; prefill: string } | null;
  /** The agent using the prompt that the finding is about. */
  agent: { id: string; name: string } | null;
  source: 'model' | 'server';
  /** A server finding's `prompt_checks` code. */
  code: string | null;
  /** A server finding's text (the placeholder, the variables). */
  text: string | null;
};

export type PromptReviewProposal = Omit<PromptImproveProposal, 'mode'> & {
  mode: 'review';
  findings: ReviewFinding[];
  /** The checks with no finding, in the checklist's order. */
  passed: ReviewCheck[];
};

export type PromptProposal =
  PromptImproveProposal | PromptReviewProposal | PromptWriteProposal;

/**
 * `improve` for a prompt with text, `write` for an empty one, saved or new
 * (the server has nothing to improve in an empty prompt). Empty as the
 * server reads it: zero-width and control characters count as nothing.
 */
export function promptDrafterMode(content: string): 'improve' | 'write' {
  return promptAsRead(content) ? 'improve' : 'write';
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(isString) : [];
}

function checks(value: unknown): PromptCheck[] {
  return strings(value).filter((code): code is PromptCheck =>
    PROMPT_CHECKS.includes(code as PromptCheck),
  );
}

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

const text = (value: unknown): string => (isString(value) ? value : '');

/**
 * A review's `findings`, malformed ones dropped: each needs an id and a
 * severity, and a title unless the server words it by `code`. An `edit`
 * that names no edit of the proposal, a malformed `ask` or `agent`, is
 * dropped from its finding.
 */
function readFindings(raw: unknown, edits: PromptEdit[]): ReviewFinding[] {
  if (!Array.isArray(raw)) return [];
  const editIds = new Set(edits.map((edit) => edit.id));
  return raw.flatMap((item): ReviewFinding[] => {
    const value = asRecord(item);
    if (!value || !isString(value.id)) return [];
    if (value.severity !== 'fix' && value.severity !== 'look') return [];
    const source = value.source === 'server' ? 'server' : 'model';
    const code = isString(value.code) && value.code ? value.code : null;
    const title = text(value.title).trim();
    if (source === 'server' ? !code : !title) return [];
    const ask = asRecord(value.ask);
    const agent = asRecord(value.agent);
    return [
      {
        id: value.id,
        check: text(value.check),
        severity: value.severity,
        title,
        detail: text(value.detail).trim(),
        edit:
          isString(value.edit) && editIds.has(value.edit) ? value.edit : null,
        ask:
          ask && isString(ask.label) && ask.label.trim()
            ? { label: ask.label, prefill: text(ask.prefill) }
            : null,
        agent:
          agent && isString(agent.id) && isString(agent.name) && agent.name
            ? { id: agent.id, name: agent.name }
            : null,
        source,
        code,
        text: isString(value.text) && value.text ? value.text : null,
      },
    ];
  });
}

const passedChecks = (raw: unknown): ReviewCheck[] => {
  const given = new Set(strings(raw));
  return REVIEW_CHECKS.filter((check) => given.has(check));
};

/** A proposal's `checks`, unknown codes dropped. */
export const readPromptChecks = (raw: unknown): PromptCheck[] => checks(raw);

/**
 * A `proposal` event's payload as a prompt proposal.
 *
 * Args:
 *   raw: The payload.
 *
 * Returns:
 *   The proposal, or null when it isn't one.
 */
export function readPromptProposal(raw: unknown): PromptProposal | null {
  if (!raw || typeof raw !== 'object') return null;
  const value = raw as Record<string, unknown>;
  const message = isString(value.message) ? value.message : '';
  if (value.mode === 'improve' && Array.isArray(value.edits)) {
    return {
      mode: 'improve',
      message,
      edits: readPromptEdits(value.edits),
      warnings: strings(value.warnings),
      checks: checks(value.checks),
      suggestions: strings(value.suggestions),
    };
  }
  if (value.mode === 'review') {
    const edits = readPromptEdits(value.edits);
    return {
      mode: 'review',
      message,
      edits,
      findings: readFindings(value.findings, edits),
      passed: passedChecks(value.passed),
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

// What the server's clean_text (docsgpt/drafter/fencing.py) drops before the
// model reads the text, kept in step with it: control characters but \n and
// \t, lone surrogates, invisible format characters, and tag characters
// outside a subdivision flag.
const INVISIBLE = new Set(
  '\u200b\u202a\u202b\u202c\u202d\u202e\u2060\u2061\u2062\u2063\u2064' +
    '\u2066\u2067\u2068\u2069\u206a\u206b\u206c\u206d\u206e\u206f\ufeff\ufff9\ufffa\ufffb',
);
const FLAG = '\u{1F3F4}';
const FLAG_END = '\u{E007F}';

const dropped = (ch: string): boolean => {
  const code = ch.codePointAt(0) ?? 0;
  const control =
    (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) &&
    ch !== '\n' &&
    ch !== '\t';
  return control || (code >= 0xd800 && code <= 0xdfff) || INVISIBLE.has(ch);
};
const isTag = (ch: string): boolean => {
  const code = ch.codePointAt(0) ?? 0;
  return code >= 0xe0000 && code <= 0xe007f;
};
const isFlagLetter = (ch: string | undefined): boolean => {
  const code = ch?.codePointAt(0) ?? 0;
  return (
    (code >= 0xe0030 && code <= 0xe0039) || (code >= 0xe0061 && code <= 0xe007a)
  );
};

/** The text as the server reads it, and where each of its code units sits in the text as it is. */
type ReadText = { text: string; at: number[] };

function readText(content: string): ReadText {
  const chars: [string, number][] = [];
  let offset = 0;
  for (const ch of content) {
    if (!dropped(ch)) chars.push([ch, offset]);
    offset += ch.length;
  }
  // A subdivision flag (England, Scotland, Wales) keeps its tag sequence.
  const flagged = new Set<number>();
  chars.forEach(([ch], index) => {
    if (ch !== FLAG) return;
    let end = index + 1;
    while (end - index <= 6 && isFlagLetter(chars[end]?.[0])) end += 1;
    if (end - index - 1 < 3 || chars[end]?.[0] !== FLAG_END) return;
    for (let at = index + 1; at <= end; at += 1) flagged.add(at);
  });
  const kept = chars.filter(([ch], index) => !isTag(ch) || flagged.has(index));
  // Trimmed, as the server strips it.
  let from = 0;
  let to = kept.length;
  while (from < to && /\s/u.test(kept[from][0])) from += 1;
  while (to > from && /\s/u.test(kept[to - 1][0])) to -= 1;
  const read: ReadText = { text: '', at: [] };
  kept.slice(from, to).forEach(([ch, at]) => {
    read.text += ch;
    for (let unit = 0; unit < ch.length; unit += 1) read.at.push(at + unit);
  });
  return read;
}

/**
 * The text as the server reads it for its edits: cleaned of control and
 * invisible characters (a Windows line end is a plain `\n` there) and
 * trimmed. The edits' text is in this form; the functions below map it back
 * onto the text as it is.
 *
 * Args:
 *   content: The prompt's text.
 *
 * Returns:
 *   The text the server's edits fit.
 */
export const promptAsRead = (content: string): string => readText(content).text;

type Located = { edit: PromptEdit; start: number; end: number };

/**
 * Each edit's place in `content`, in edit order: where its text occurs in
 * the text as read, as a span of `content` (taking in the characters the
 * reading dropped inside it). `once` is whether it occurs only there.
 */
function placeEdits(
  content: string,
  edits: PromptEdit[],
): (Located & { once: boolean })[] {
  const { text, at } = readText(content);
  return edits.flatMap((edit) => {
    const found = edit.find ? text.indexOf(edit.find) : -1;
    if (found < 0) return [];
    const last = found + edit.find.length - 1;
    return [
      {
        edit,
        start: at[found],
        end: at[last] + 1,
        once: text.indexOf(edit.find, found + 1) < 0,
      },
    ];
  });
}

/** Each edit's place in `content`, in text order; an edit whose text is gone is left out. */
function locate(content: string, edits: PromptEdit[]): Located[] {
  return placeEdits(content, edits).sort((a, b) => a.start - b.start);
}

/**
 * The edits that still fit `content`: each one's text occurs there exactly
 * once (as the server reads it) and overlaps no edit kept before it. The
 * server checked them against the text the model read; the text here can
 * differ (edited while the model worked, or saved since).
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
  return placeEdits(content, edits)
    .filter(({ start, end, once }) => {
      if (!once || taken.some(([from, to]) => start < to && from < end))
        return false;
      taken.push([start, end]);
      return true;
    })
    .map(({ edit }) => edit);
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
    out += accepted(edit.id) ? edit.replace : content.slice(start, end);
    cursor = end;
  }
  return out + content.slice(cursor);
}

export type PromptDiffSegment =
  | { kind: 'text'; text: string }
  | {
      kind: 'change';
      edit: PromptEdit;
      number: number;
      /** The whole words the edit's find and replace share at each end. */
      kept: { before: string; after: string };
      /** What goes, between the kept words. */
      removed: string;
      /** What comes in, between the kept words. */
      added: string;
    };

/** A text as whole words and the runs of space between them. */
const words = (text: string): string[] => text.match(/\s+|\S+/g) ?? [];

/**
 * Split a change into the whole words its find and replace share at the
 * start and at the end, and the part that really changes: a model that adds
 * text after a line sends the line in both, which then reads as an addition
 * instead of the line struck and added back.
 */
function trimChange(
  find: string,
  replace: string,
): { kept: { before: string; after: string }; removed: string; added: string } {
  const from = words(find);
  const to = words(replace);
  let start = 0;
  while (start < from.length && start < to.length && from[start] === to[start])
    start += 1;
  let end = 0;
  while (
    end < from.length - start &&
    end < to.length - start &&
    from[from.length - 1 - end] === to[to.length - 1 - end]
  )
    end += 1;
  return {
    kept: {
      before: from.slice(0, start).join(''),
      after: from.slice(from.length - end).join(''),
    },
    removed: from.slice(start, from.length - end).join(''),
    added: to.slice(start, to.length - end).join(''),
  };
}

/**
 * The text cut into unchanged runs and changes, each change numbered in text
 * order (the number the review's list uses), with the whole words it shares
 * with what it replaces kept apart from what really changes.
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
    segments.push({
      kind: 'change',
      edit,
      number,
      ...trimChange(edit.find, edit.replace),
    });
    cursor = end;
  }
  if (cursor < content.length)
    segments.push({ kind: 'text', text: content.slice(cursor) });
  return segments;
}
