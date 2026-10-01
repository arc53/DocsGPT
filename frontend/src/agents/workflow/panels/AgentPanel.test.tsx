import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { type Node } from 'reactflow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AgentPanel from './AgentPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeNode = (config: Record<string, unknown> = {}): Node => ({
  id: 'agent_1',
  type: 'agent',
  position: { x: 0, y: 0 },
  data: {
    title: 'Classify',
    config: {
      agent_type: 'classic',
      system_prompt: '',
      prompt_template: '',
      stream_to_user: true,
      sources: [],
      tools: [],
      ...config,
    },
  },
});

describe('AgentPanel', () => {
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
    document.body.innerHTML = '';
  });

  const render = (node: Node, jsonSchemaText = '') => {
    const onUpdate = vi.fn();
    act(() => {
      root.render(
        <AgentPanel
          node={node}
          onUpdate={onUpdate}
          nodes={[node]}
          edges={[]}
          availableModels={[]}
          availableTools={[]}
          sourceOptions={[]}
          documentOptions={[]}
          jsonSchemaText={jsonSchemaText}
          jsonSchemaError={null}
          modelSupportsStructuredOutput
          onJsonSchemaChange={vi.fn()}
        />,
      );
    });
    return { onUpdate };
  };

  const advancedToggle = () =>
    Array.from(container.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.workflow.builder.advancedSettings'),
    ) as HTMLButtonElement;

  it('groups the fields under Model, Prompt, Knowledge and Output', () => {
    render(makeNode());
    const headings = Array.from(container.querySelectorAll('h3')).map(
      (h) => h.textContent,
    );
    expect(headings).toEqual([
      'agents.form.sections.model',
      'agents.form.sections.prompt',
      'agents.workflow.builder.knowledge',
      'agents.workflow.builder.output',
    ]);
  });

  it('stacks Agent type and Model at full width in the narrow panel', () => {
    render(makeNode());
    const modelSection = container.querySelector('section')!;
    expect(modelSection.querySelector('.grid')).toBeNull();
    const triggers = modelSection.querySelectorAll('[role="combobox"]');
    expect(triggers).toHaveLength(2);
    triggers.forEach((trigger) =>
      expect(trigger.className).toContain('w-full'),
    );
  });

  it('streams through a Switch with a description, not a Checkbox', () => {
    const { onUpdate } = render(makeNode());
    expect(container.querySelector('[role="checkbox"]')).toBeNull();
    const toggle = container.querySelector(
      '[role="switch"]',
    ) as HTMLButtonElement;
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(container.textContent).toContain(
      'agents.workflow.builder.streamToUserDescription',
    );
    act(() => toggle.click());
    expect(onUpdate).toHaveBeenCalledWith({
      config: expect.objectContaining({ stream_to_user: false }),
    });
  });

  it('keeps advanced settings closed when none is set', () => {
    render(makeNode());
    const toggle = advancedToggle();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    // Folded: the fields wait in a closed, inert Collapsible.
    const body = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    )!;
    expect(body.dataset.state).toBe('closed');
    expect(body.hasAttribute('inert')).toBe(true);
    act(() => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
    expect(container.textContent).toContain(
      'agents.workflow.builder.filePassing',
    );
  });

  it('opens advanced settings when one of them is set', () => {
    render(makeNode({ file_passing: 'native' }));
    expect(advancedToggle().getAttribute('aria-expanded')).toBe('true');
  });

  it('opens advanced settings when a schema is present', () => {
    render(makeNode({ json_schema: { type: 'object' } }), '{"type":"object"}');
    expect(advancedToggle().getAttribute('aria-expanded')).toBe('true');
  });
});
