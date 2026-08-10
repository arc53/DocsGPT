import { ToolCallsType } from './types';

/**
 * Ordering layer only: ``response``/``thought``/``tool_calls`` keep accumulating
 * as before and stay the source of truth for copy, feedback, history and resume.
 */
export type AnswerSegment =
  | { kind: 'thought'; text: string }
  // Id only. The call is upserted in place in ``query.tool_calls``, so a chip
  // always reads its current status rather than a frozen copy.
  | { kind: 'tool'; call_id: string };

export function appendThoughtText(
  segments: AnswerSegment[],
  delta: string,
): void {
  const last = segments[segments.length - 1];
  if (last?.kind === 'thought') last.text += delta;
  else segments.push({ kind: 'thought', text: delta });
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

/** Fallback order for answers with no recorded arrival order (reloads, shares). */
export function synthesizeSegments(query: {
  thought?: string;
  tool_calls?: ToolCallsType[];
}): AnswerSegment[] {
  const segments: AnswerSegment[] = [];
  if (query.thought) segments.push({ kind: 'thought', text: query.thought });
  query.tool_calls?.forEach((call) => {
    if (call.call_id) segments.push({ kind: 'tool', call_id: call.call_id });
  });
  return segments;
}

/**
 * Whether the recorded order still accounts for every part of the answer. A
 * call with no id can never be recorded, so it never counts against the order.
 */
function coversAnswer(
  query: { thought?: string; tool_calls?: ToolCallsType[] },
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
  const orderedThought = segments
    .flatMap((segment) => (segment.kind === 'thought' ? [segment.text] : []))
    .join('');
  return everyCallOrdered && orderedThought === (query.thought ?? '');
}

export function getAnswerSegments(query: {
  thought?: string;
  tool_calls?: ToolCallsType[];
  segments?: AnswerSegment[];
}): AnswerSegment[] {
  // The order only arranges what ``thought``/``tool_calls`` already hold, so one
  // that no longer accounts for them (a tail snapshot landed mid-stream, a
  // reconnect replayed part of it) loses to synthesis rather than hiding the
  // steps it never recorded.
  if (query.segments?.length && coversAnswer(query, query.segments))
    return query.segments;
  return synthesizeSegments(query);
}
