import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { type Node } from 'reactflow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  Trans: ({ i18nKey }: { i18nKey: string }) => i18nKey,
}));

import ConditionPanel from './ConditionPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const node: Node = {
  id: 'condition_1',
  type: 'condition',
  position: { x: 0, y: 0 },
  data: {
    title: 'Route',
    config: {
      mode: 'simple',
      cases: [
        {
          name: 'People Ops',
          expression: 'category.contains("people")',
          sourceHandle: 'case_0',
        },
      ],
    },
  },
};

describe('ConditionPanel', () => {
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
      root.render(
        <ConditionPanel
          node={node}
          onUpdate={onUpdate}
          onRemoveBranch={vi.fn()}
        />,
      );
    });
    return { onUpdate };
  };

  it('picks the mode with a ToggleGroup that fills its row', () => {
    const { onUpdate } = render();
    const group = container.querySelector('[role="radiogroup"]')!;
    // The group draws its own track; no hand-built wrapper around it.
    expect(group.className).toContain('bg-muted');
    expect(group.classList.contains('w-full')).toBe(true);
    expect(group.parentElement!.className).not.toContain('bg-muted');
    const advanced = Array.from(group.querySelectorAll('button')).find(
      (b) => b.textContent === 'agents.workflow.builder.modeAdvanced',
    )!;
    act(() => advanced.click());
    expect(onUpdate).toHaveBeenCalledWith({
      config: expect.objectContaining({ mode: 'advanced' }),
    });
  });

  it('labels the branch name, variable, operator and value fields', () => {
    render();
    const labels = Array.from(
      container.querySelectorAll('[data-slot="form-field-label"]'),
    ).map((l) => l.textContent);
    expect(labels).toEqual([
      'agents.workflow.builder.branchName',
      'agents.workflow.builder.variable',
      'agents.workflow.builder.operator',
      'agents.workflow.builder.value',
    ]);
  });

  it('wires the operator label to its select, with no aria-label', () => {
    render();
    const trigger = container.querySelector('[role="combobox"]')!;
    expect(trigger.hasAttribute('aria-label')).toBe(false);
    const label = container.querySelector(`label[for="${trigger.id}"]`);
    expect(label?.textContent).toBe('agents.workflow.builder.operator');
  });

  it('adds a condition with an outline pill button', () => {
    const { onUpdate } = render();
    const add = Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.workflow.builder.addCondition'),
    )!;
    expect(add.getAttribute('data-variant')).toBe('outline');
    act(() => add.click());
    const cases = onUpdate.mock.calls[0][0].config.cases;
    expect(cases).toHaveLength(2);
    expect(cases[1].sourceHandle).toBe('case_1');
  });
});
