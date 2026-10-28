import { WorkflowProgress, WorkflowStep } from './conversationModels';

// Nodes that do no work a person would follow: the run's entry and exit, and
// sticky notes on the canvas.
const HIDDEN_NODE_TYPES = new Set(['start', 'end', 'note']);
const DETAIL_MAX = 140;

/** A ``workflow_step`` stream event, as the engine sends it. */
export type WorkflowStepEvent = {
  node_id: string;
  node_type: string;
  node_title?: string;
  status: 'running' | 'completed' | 'failed';
  output?: unknown;
  state_delta?: Record<string, unknown>;
  error?: string;
};

function oneLine(value: unknown): string {
  if (value === undefined || value === null) return '';
  const text =
    typeof value === 'string'
      ? value
      : (JSON.stringify(value) ?? String(value));
  // Markdown markers read as noise on a one-line summary.
  const line = text
    .replace(/^#+\s+|\*\*|__|`/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
  return line.length > DETAIL_MAX ? `${line.slice(0, DETAIL_MAX - 1)}…` : line;
}

/**
 * One line about a finished step: an agent's or code node's output, else the
 * state values it set (``tone: friendly``). Internal keys are left out.
 */
export function stepDetail(event: WorkflowStepEvent): string | undefined {
  const output = oneLine(event.output);
  if (output) return output;
  const entries = Object.entries(event.state_delta ?? {}).filter(
    ([key]) =>
      !['query', 'chat_history', 'input_documents', 'passthrough'].includes(
        key,
      ) && !key.startsWith('node_'),
  );
  if (entries.length === 0) return undefined;
  return oneLine(
    entries.map(([key, value]) => `${key}: ${oneLine(value)}`).join(' · '),
  );
}

/**
 * Applies one ``workflow_step`` event to a turn's progress, in place. Steps
 * keep the order they started in; start, end and note nodes are skipped.
 * ``answer`` is the turn's streamed text, so the step that wrote it gets no
 * detail line.
 */
export function applyWorkflowStep(
  progress: WorkflowProgress,
  event: WorkflowStepEvent,
  now: number,
  answer?: string,
): void {
  if (HIDDEN_NODE_TYPES.has(event.node_type)) return;
  const existing = progress.steps.find((s) => s.nodeId === event.node_id);
  const step: WorkflowStep = existing ?? {
    nodeId: event.node_id,
    nodeType: event.node_type,
    title: event.node_title || event.node_type,
    status: 'running',
    startedAt: now,
  };
  step.status = event.status;
  if (event.node_title) step.title = event.node_title;
  if (event.status === 'running') {
    step.startedAt = now;
    step.endedAt = undefined;
  } else {
    step.endedAt = now;
    // The step that wrote the answer would only repeat its first line.
    const wroteAnswer =
      Boolean(answer?.trim()) &&
      typeof event.output === 'string' &&
      event.output.trim() === answer?.trim();
    step.detail = wroteAnswer ? undefined : stepDetail(event);
    if (event.error) step.error = event.error;
  }
  if (!existing) progress.steps.push(step);
}

/** The step still working, if any. */
export function runningStep(
  progress?: WorkflowProgress,
): WorkflowStep | undefined {
  return progress?.steps.findLast((s) => s.status === 'running');
}
