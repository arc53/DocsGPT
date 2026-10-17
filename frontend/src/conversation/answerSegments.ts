import { ToolCallsType } from './types';

/**
 * Ordering layer only: ``response``/``thought``/``tool_calls`` keep accumulating
 * as before and stay the source of truth for copy, feedback, history and resume.
 */
export type AnswerSegment =
  | { kind: 'thought'; text: string }
  // A stretch of the answer between steps: the model's narration between calls,
  // or the answer itself.
  | { kind: 'text'; text: string }
  // Id only. The call is upserted in place in ``query.tool_calls``, so a chip
  // always reads its current status rather than a frozen copy.
  | { kind: 'tool'; call_id: string };

function appendText(
  segments: AnswerSegment[],
  kind: 'thought' | 'text',
  delta: string,
): void {
  if (!delta) return;
  const last = segments[segments.length - 1];
  if (last?.kind === kind) last.text += delta;
  else segments.push({ kind, text: delta });
}

export function appendThoughtText(
  segments: AnswerSegment[],
  delta: string,
): void {
  appendText(segments, 'thought', delta);
}

export function appendAnswerText(
  segments: AnswerSegment[],
  delta: string,
): void {
  appendText(segments, 'text', delta);
}

export function recordToolCall(
  segments: AnswerSegment[],
  callId: string,
): void {
  if (!callId) return;
  // Each call arrives twice (pending, then completed); only the first fixes
  // its position.
  const seen = segments.some(
    (segment) => segment.kind === 'tool' && segment.call_id === callId,
  );
  if (!seen) segments.push({ kind: 'tool', call_id: callId });
}

/**
 * The order the backend saved with the message (``metadata.segments``), where a
 * text or thought segment is a length in UTF-16 units, turned back into
 * segments by slicing the saved response and reasoning in turn.
 *
 * @returns The segments, or ``undefined`` when the saved order is missing or
 * does not fit what was saved (``getAnswerSegments`` then synthesizes one).
 */
export function hydrateSegments(
  stored: unknown,
  response: string | undefined,
  thought: string | undefined,
): AnswerSegment[] | undefined {
  if (!Array.isArray(stored) || stored.length === 0) return undefined;
  const sources = { text: response ?? '', thought: thought ?? '' };
  const offsets = { text: 0, thought: 0 };
  const segments: AnswerSegment[] = [];
  for (const item of stored) {
    if (item?.kind === 'tool' && typeof item.call_id === 'string') {
      segments.push({ kind: 'tool', call_id: item.call_id });
      continue;
    }
    const kind = item?.kind as 'text' | 'thought';
    const length = item?.length;
    if ((kind !== 'text' && kind !== 'thought') || !Number.isInteger(length))
      return undefined;
    const end = offsets[kind] + length;
    if (end > sources[kind].length) return undefined;
    segments.push({ kind, text: sources[kind].slice(offsets[kind], end) });
    offsets[kind] = end;
  }
  return segments;
}

/** Fallback order for answers with no recorded arrival order (reloads, shares). */
export function synthesizeSegments(query: {
  thought?: string;
  tool_calls?: ToolCallsType[];
  response?: string;
}): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  if (query.thought) segments.push({ kind: 'thought', text: query.thought });
  query.tool_calls?.forEach((call) => {
    if (call.call_id) segments.push({ kind: 'tool', call_id: call.call_id });
  });
  if (query.response) segments.push({ kind: 'text', text: query.response });
  return segments;
}

const joined = (segments: AnswerSegment[], kind: 'thought' | 'text') =>
  segments
    .flatMap((segment) => (segment.kind === kind ? [segment.text] : []))
    .join('');

/**
 * Whether the recorded order still accounts for every part of the answer. A
 * call with no id can never be recorded, so it never counts against the order.
 * An order with no text at all (a stream that recorded steps only) is checked
 * on its steps; the answer then goes after them.
 */
function coversAnswer(
  query: { thought?: string; tool_calls?: ToolCallsType[]; response?: string },
  segments: AnswerSegment[],
): boolean {
  const ordered = new Set(
    segments.flatMap((segment) =>
      segment.kind === 'tool' ? [segment.call_id] : [],
    ),
  );
  const everyCallOrdered = (query.tool_calls ?? []).every(
    (call) => !call.call_id || ordered.has(call.call_id),
  );
  const hasText = segments.some((segment) => segment.kind === 'text');
  return (
    everyCallOrdered &&
    joined(segments, 'thought') === (query.thought ?? '') &&
    (!hasText || joined(segments, 'text') === (query.response ?? ''))
  );
}

export function getAnswerSegments(query: {
  thought?: string;
  tool_calls?: ToolCallsType[];
  segments?: AnswerSegment[];
  response?: string;
}): AnswerSegment[] {
  // The order only arranges what ``thought``/``tool_calls``/``response`` already
  // hold, so one that no longer accounts for them (a tail snapshot landed
  // mid-stream, a reconnect replayed part of it, a guardrail replaced the
  // answer) loses to synthesis rather than hiding the parts it never recorded.
  const { segments } = query;
  if (!segments?.length || !coversAnswer(query, segments))
    return synthesizeSegments(query);
  if (!query.response || segments.some((segment) => segment.kind === 'text'))
    return segments;
  return [...segments, { kind: 'text', text: query.response }];
}
