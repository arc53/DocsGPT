import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { type Node } from 'reactflow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { index?: number }) =>
      opts?.index !== undefined ? `${key}:${opts.index}` : key,
  }),
  Trans: ({ i18nKey }: { i18nKey: string }) => i18nKey,
}));

import StatePanel from './StatePanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const node: Node = {
  id: 'state_1',
  type: 'state',
  position: { x: 0, y: 0 },
  data: {
    title: 'Set priority',
    config: {
      operations: [
        { expression: '"P1"', target_variable: 'priority' },
        { expression: '"4h"', target_variable: 'sla' },
      ],
    },
  },
};

describe('StatePanel', () => {
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

  const render = () => {
    const onUpdate = vi.fn();
    act(() => {
      root.render(<StatePanel node={node} onUpdate={onUpdate} />);
    });
    return { onUpdate };
  };

  it('explains CEL once, in the intro', () => {
    render();
    const matches = container.textContent!.match(
      /agents\.workflow\.builder\.celHint/g,
    );
    expect(matches).toHaveLength(1);
    expect(
      container.querySelectorAll('a[href="https://cel.dev/"]'),
    ).toHaveLength(1);
  });

  it('numbers each assignment and puts the variable before the value', () => {
    render();
    expect(container.textContent).toContain(
      'agents.workflow.builder.assignment:1',
    );
    expect(container.textContent).toContain(
      'agents.workflow.builder.assignment:2',
    );
    const labels = Array.from(
      container.querySelectorAll('[data-slot="form-field-label"]'),
    ).map((l) => l.textContent);
    expect(labels.slice(0, 2)).toEqual([
      'agents.workflow.builder.variable',
      'agents.workflow.builder.valueCel',
    ]);
  });

  it('adds an assignment with an outline pill button', () => {
    const { onUpdate } = render();
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.workflow.builder.addAssignment'),
    )!;
    expect(add.getAttribute('data-variant')).toBe('outline');
    act(() => add.click());
    expect(onUpdate.mock.calls[0][0].config.operations).toHaveLength(3);
  });
});
