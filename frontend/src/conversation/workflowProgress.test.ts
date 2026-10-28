import { describe, expect, it } from 'vitest';

import { WorkflowProgress } from './conversationModels';
import {
  applyWorkflowStep,
  runningStep,
  stepDetail,
  WorkflowStepEvent,
} from './workflowProgress';

const event = (
  overrides: Partial<WorkflowStepEvent> = {},
): WorkflowStepEvent => ({
  node_id: 'a',
  node_type: 'agent',
  node_title: 'Gather notes',
  status: 'running',
  ...overrides,
});

describe('stepDetail', () => {
  it('summarises the output on one line without markdown markers', () => {
    expect(
      stepDetail(event({ output: '## Notes\n\n**Alps** are\n`high`' })),
    ).toBe('Notes Alps are high');
  });

  it('cuts a long output short', () => {
    const detail = stepDetail(event({ output: 'x'.repeat(500) }))!;
    expect(detail).toHaveLength(140);
    expect(detail.endsWith('…')).toBe(true);
  });

  it('lists the state a step set, leaving internal keys out', () => {
    expect(
      stepDetail(
        event({
          state_delta: {
            tone: 'friendly',
            days: 2,
            query: 'q',
            node_a_output: 'x',
          },
        }),
      ),
    ).toBe('tone: friendly · days: 2');
  });

  it('has nothing to say about a step that changed nothing', () => {
    expect(stepDetail(event({ state_delta: { query: 'q' } }))).toBeUndefined();
  });
});

describe('applyWorkflowStep', () => {
  it('adds a step when it starts and closes it when it ends', () => {
    const progress: WorkflowProgress = { steps: [] };
    applyWorkflowStep(progress, event(), 1000);
    applyWorkflowStep(
      progress,
      event({ status: 'completed', output: 'three notes' }),
      4000,
    );
    expect(progress.steps).toEqual([
      {
        nodeId: 'a',
        nodeType: 'agent',
        title: 'Gather notes',
        status: 'completed',
        startedAt: 1000,
        endedAt: 4000,
        detail: 'three notes',
      },
    ]);
  });

  it('skips the start, end and note nodes', () => {
    const progress: WorkflowProgress = { steps: [] };
    for (const type of ['start', 'end', 'note'])
      applyWorkflowStep(progress, event({ node_type: type }), 0);
    expect(progress.steps).toEqual([]);
  });

  it('keeps the error of a failed step', () => {
    const progress: WorkflowProgress = { steps: [] };
    applyWorkflowStep(progress, event(), 0);
    applyWorkflowStep(
      progress,
      event({ status: 'failed', error: 'model timed out' }),
      10,
    );
    expect(progress.steps[0]).toMatchObject({
      status: 'failed',
      error: 'model timed out',
    });
  });

  it('gives the step that wrote the answer no detail line', () => {
    const progress: WorkflowProgress = { steps: [] };
    applyWorkflowStep(progress, event(), 0);
    applyWorkflowStep(
      progress,
      event({ status: 'completed', output: 'The answer.' }),
      10,
      'The answer.',
    );
    expect(progress.steps[0].detail).toBeUndefined();
  });
});

describe('runningStep', () => {
  it('is the step still working', () => {
    const progress: WorkflowProgress = { steps: [] };
    applyWorkflowStep(progress, event(), 0);
    applyWorkflowStep(progress, event({ status: 'completed' }), 1);
    expect(runningStep(progress)).toBeUndefined();
    applyWorkflowStep(progress, event({ node_id: 'b', node_title: 'B' }), 2);
    expect(runningStep(progress)?.nodeId).toBe('b');
  });
});
