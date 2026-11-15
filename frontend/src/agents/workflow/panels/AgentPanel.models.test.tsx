import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { type Node } from 'reactflow';

import type { Model } from '../../../models/types';

vi.mock('../../../modals/AddToolModal', () => ({ default: () => null }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      preference: { token: null, sourceDocs: [] },
      connectors: { connections: [], catalog: [] },
    }),
  useDispatch: () => vi.fn(),
}));
// A plain stand-in for the Radix select: every group and item renders.
vi.mock('@/components/ui/select', () => {
  const Pass = ({ children }: { children?: React.ReactNode }) => (
    <div>{children}</div>
  );
  return {
    Select: Pass,
    SelectTrigger: Pass,
    SelectValue: () => null,
    SelectContent: Pass,
    SelectGroup: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="group">{children}</div>
    ),
    SelectLabel: ({ children }: { children: React.ReactNode }) => (
      <span data-testid="group-label">{children}</span>
    ),
    SelectItem: ({ children }: { children: React.ReactNode }) => (
      <span data-testid="item">{children}</span>
    ),
  };
});

import AgentPanel from './AgentPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const node: Node = {
  id: 'agent_1',
  type: 'agent',
  position: { x: 0, y: 0 },
  data: {
    title: 'Classify',
    config: {
      agent_type: 'classic',
      system_prompt: '',
      sources: [],
      tools: [],
    },
  },
};

const MODELS: Model[] = [
  {
    id: 'gpt-a',
    value: 'gpt-a',
    provider: 'openai',
    display_name: 'GPT A',
    source: 'builtin',
  },
  {
    id: 'llama',
    value: 'llama',
    provider: 'openai',
    display_name: 'Llama',
    source: 'user',
  },
] as Model[];

describe('AgentPanel model picker', () => {
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

  const groupLabels = (modelsFromOwner?: boolean) => {
    act(() => {
      root.render(
        <AgentPanel
          node={node}
          onUpdate={vi.fn()}
          nodes={[node]}
          edges={[]}
          availableModels={MODELS}
          modelsFromOwner={modelsFromOwner}
          availableTools={[]}
          documentOptions={[]}
          jsonSchemaText=""
          jsonSchemaError={null}
          modelSupportsStructuredOutput
          onJsonSchemaChange={vi.fn()}
          onReloadTools={vi.fn(async () => [])}
        />,
      );
    });
    return Array.from(
      container.querySelectorAll('[data-testid="group-label"]'),
    ).map((label) => label.textContent);
  };

  it("groups the caller's custom models under My Models", () => {
    expect(groupLabels()).toContain('settings.customModels.modelsGroup.user');
  });

  it("names a team editor's custom models as the owner's", () => {
    const labels = groupLabels(true);
    expect(labels).toContain('settings.customModels.modelsGroup.owner');
    expect(labels).not.toContain('settings.customModels.modelsGroup.user');
  });
});
