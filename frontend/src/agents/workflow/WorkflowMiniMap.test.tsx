import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { WorkflowNode } from '../types/workflow';
import type { WorkflowExecutionStep } from './workflowPreviewSlice';
import { WorkflowMiniMap } from './WorkflowPreview';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const node = (
  id: string,
  type: WorkflowNode['type'],
  y: number,
): WorkflowNode => ({
  id,
  type,
  title: id,
  position: { x: 0, y },
  data: {},
});

const nodes = [
  node('start', 'start', 0),
  node('done', 'agent', 1),
  node('broken', 'agent', 2),
  node('busy', 'agent', 3),
];

const step = (
  nodeId: string,
  status: WorkflowExecutionStep['status'],
): WorkflowExecutionStep => ({
  nodeId,
  nodeType: 'agent',
  nodeTitle: nodeId,
  status,
});

const steps = [
  step('done', 'completed'),
  step('broken', 'failed'),
  step('busy', 'running'),
];

describe('WorkflowMiniMap', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const rows = (activeNodeId: string | null = null) => {
    act(() => {
      root.render(
        <WorkflowMiniMap
          nodes={nodes}
          activeNodeId={activeNodeId}
          executionSteps={steps}
        />,
      );
    });
    const byName: Record<string, HTMLButtonElement> = {};
    container.querySelectorAll<HTMLButtonElement>('button').forEach((b) => {
      byName[b.textContent ?? ''] = b;
    });
    return byName;
  };

  // No i18n instance in this test: t() renders the key.
  const START = 'agents.workflow.nodes.start';

  const tokens = (el: HTMLElement) => el.className.split(/\s+/);

  it('pins the success fill on hover for a completed row', () => {
    const done = tokens(rows().done);
    expect(done).toEqual(
      expect.arrayContaining([
        'bg-success/10',
        'hover:bg-success/10',
        'dark:hover:bg-success/10',
        'hover:opacity-80',
      ]),
    );
    expect(done).not.toContain('hover:bg-accent');
    expect(done).not.toContain('dark:hover:bg-input/50');
  });

  it('pins each status fill on hover', () => {
    const r = rows();
    expect(tokens(r.broken)).toEqual(
      expect.arrayContaining([
        'hover:bg-destructive/10',
        'dark:hover:bg-destructive/10',
      ]),
    );
    expect(tokens(r.busy)).toEqual(
      expect.arrayContaining([
        'hover:bg-primary/10',
        'dark:hover:bg-primary/10',
        'animate-pulse',
      ]),
    );
    expect(tokens(r[START])).toEqual(
      expect.arrayContaining([
        'bg-muted',
        'hover:bg-muted',
        'dark:hover:bg-muted',
      ]),
    );
    expect(r[START].disabled).toBe(true);
    expect(tokens(r[START])).not.toContain('hover:opacity-80');
  });

  it('pins the active fill on hover and keeps the ring', () => {
    const done = tokens(rows('done').done);
    expect(done).toEqual(
      expect.arrayContaining([
        'ring-2',
        'ring-primary',
        'hover:bg-primary/10',
        'dark:hover:bg-primary/10',
      ]),
    );
    expect(done).not.toContain('hover:bg-accent');
  });
});
