import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { Node } from 'reactflow';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'name' in opts ? `${key}:${opts.name}` : key,
  }),
}));

type Option = { value: string; label: string; description?: string };
const pickers = vi.hoisted(() => [] as { options: Option[] }[]);
vi.mock('@/components/ui/multi-select', () => ({
  MultiSelect: (props: {
    options: Option[];
    selected: string[];
    onChange: (next: string[]) => void;
  }) => {
    pickers.push(props);
    return (
      <div data-testid="multi-select">
        {props.options.map((option) => (
          <button
            key={option.value}
            type="button"
            data-option={option.value}
            onClick={() =>
              props.onChange(props.selected.filter((v) => v !== option.value))
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    );
  },
}));
vi.mock('../components/PromptTextArea', () => ({
  default: () => null,
  extractUpstreamVariables: () => [],
}));
vi.mock('../components/NodeDocumentsControl', () => ({ default: () => null }));

import AgentPanel from './AgentPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentPanel attached resources', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    pickers.length = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const node = {
    id: 'a1',
    type: 'agent',
    position: { x: 0, y: 0 },
    data: { config: { tools: ['mine', 'owners'], sources: ['owner-src'] } },
  } as Node;

  const render = async (onUpdate = vi.fn()) => {
    await act(async () => {
      root.render(
        <AgentPanel
          node={node}
          onUpdate={onUpdate}
          nodes={[node]}
          edges={[]}
          availableModels={[]}
          availableTools={[
            { id: 'mine', name: 'api_tool', displayName: 'My API' },
          ]}
          sourceOptions={[{ value: 'my-src', label: 'My docs' }]}
          attachedTools={[{ id: 'owners', label: 'Owner Jira' }]}
          attachedSources={[{ id: 'owner-src', label: 'Owner docs' }]}
          documentOptions={[]}
          jsonSchemaText=""
          jsonSchemaError={null}
          modelSupportsStructuredOutput={false}
          onJsonSchemaChange={vi.fn()}
        />,
      );
    });
    return onUpdate;
  };

  // An editor's pickers don't list the owner's private tools and sources;
  // those still need a row so they can be taken off the node.
  // The chip reads the plain name; only the list row says who added it.
  it('adds remove-only options for attached tools and sources', async () => {
    const onUpdate = await render();
    const options = pickers.flatMap((p) => p.options);
    for (const name of ['Owner Jira', 'Owner docs'])
      expect(options).toContainEqual(
        expect.objectContaining({
          label: name,
          description: 'agents.form.sponsors.addedByOther',
        }),
      );
    expect(
      options.find((o) => o.value === 'mine')?.description,
    ).toBeUndefined();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>('[data-option="owners"]')!
        .click(),
    );
    expect(onUpdate).toHaveBeenCalledWith({
      config: { tools: ['mine'], sources: ['owner-src'] },
    });
  });
});
