import { AnswerSegment } from './answerSegments';
import { ToolCallsType } from './types';
import { isWikiWriteCall } from './wikiToolCall';

/** A run of this many tool steps folds into one step group. */
export const MIN_GROUP_CALLS = 3;
/** Text between steps longer than this is answer, not narration. */
const NARRATION_MAX_CHARS = 400;
// A heading, list item, quote, table row or fence: the start of answer prose.
const BLOCK_START = /^\s*(#|[-*+] |\d+[.)] |>|\||```)/m;

export type GroupEntry =
  | { kind: 'call'; call: ToolCallsType; index: number }
  | { kind: 'thought'; text: string; index: number }
  | { kind: 'note'; text: string; index: number };

/** One block of the answer column; ``index`` is the first segment it came from. */
export type FlowItem =
  | { kind: 'thought'; text: string; index: number }
  | { kind: 'text'; text: string; index: number }
  | { kind: 'call'; call: ToolCallsType; index: number }
  | { kind: 'group'; entries: GroupEntry[]; index: number };

/**
 * Whether a call can sit in a step group. Approvals, wiki writes, the
 * scheduler and background jobs render as cards that carry actions, so they
 * stay in the column.
 */
export function isGroupable(call: ToolCallsType): boolean {
  return (
    call.status !== 'awaiting_approval' &&
    !isWikiWriteCall(call) &&
    call.tool_name !== 'scheduler' &&
    !call.job_id
  );
}

/**
 * Whether text the model wrote between two steps is narration ("The API
 * returned 401, trying a web search:"), which goes inside the group, rather
 * than part of the answer, which stays in the column.
 */
export function isNarration(text: string): boolean {
  const trimmed = text.trim();
  return (
    trimmed.length > 0 &&
    trimmed.length <= NARRATION_MAX_CHARS &&
    !/\n\s*\n/.test(trimmed) &&
    !BLOCK_START.test(trimmed)
  );
}

const asItem = (entry: GroupEntry): FlowItem =>
  entry.kind === 'note' ? { ...entry, kind: 'text' } : entry;

/**
 * Lays the ordered segments out as the answer column draws them: answer text,
 * single steps, and step groups for runs of ``MIN_GROUP_CALLS`` or more tool
 * calls. Reasoning and narration between a run's calls join it; whatever
 * follows its last call stays outside, so a run only grows as calls arrive.
 */
export function layoutAnswer(
  steps: AnswerSegment[],
  callById: Map<string, ToolCallsType>,
): FlowItem[] {
  const items: FlowItem[] = [];
  let run: GroupEntry[] = [];
  // Reasoning and narration after the run's latest call: they join the run
  // only if another call follows.
  let trailing: GroupEntry[] = [];

  const flush = () => {
    const calls = run.filter((entry) => entry.kind === 'call').length;
    if (calls >= MIN_GROUP_CALLS)
      items.push({ kind: 'group', entries: run, index: run[0].index });
    else items.push(...run.map(asItem));
    items.push(...trailing.map(asItem));
    run = [];
    trailing = [];
  };

  steps.forEach((step, index) => {
    if (step.kind === 'tool') {
      const call = callById.get(step.call_id);
      if (!call) return;
      if (!isGroupable(call)) {
        flush();
        items.push({ kind: 'call', call, index });
        return;
      }
      run.push(...trailing, { kind: 'call', call, index });
      trailing = [];
      return;
    }
    if (!step.text.trim()) return;
    if (step.kind === 'thought') {
      if (run.length)
        trailing.push({ kind: 'thought', text: step.text, index });
      else items.push({ kind: 'thought', text: step.text, index });
      return;
    }
    if (run.length && isNarration(step.text)) {
      trailing.push({ kind: 'note', text: step.text, index });
      return;
    }
    flush();
    items.push({ kind: 'text', text: step.text, index });
  });
  flush();

  // Two stretches of answer text from different rounds, once nothing sits
  // between them, are separate paragraphs; the rounds were never joined.
  return items.reduce<FlowItem[]>((merged, item) => {
    const last = merged[merged.length - 1];
    if (item.kind === 'text' && last?.kind === 'text')
      merged[merged.length - 1] = {
        ...last,
        text: `${last.text}\n\n${item.text}`,
      };
    else merged.push(item);
    return merged;
  }, []);
}
