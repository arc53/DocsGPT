import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useDispatch: () => vi.fn(),
  useSelector: (selector: { name?: string }) =>
    selector.name === 'selectToken' ? 'token' : [],
}));

const mockT = (key: string) => key;
const mockI18n = { language: 'en' };
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: mockT, i18n: mockI18n }),
  Trans: ({ i18nKey }: { i18nKey: string }) => <>{i18nKey}</>,
}));

// The canvas as one button per node, so a test can select one.
vi.mock('reactflow', () => {
  const noop = () => undefined;
  const flow = {
    fitView: noop,
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
    screenToFlowPosition: (p: unknown) => p,
    project: (p: unknown) => p,
    setCenter: noop,
    zoomIn: noop,
    zoomOut: noop,
    getNodes: () => [],
    getEdges: () => [],
  };
  type FlowNode = { id: string };
  return {
    default: ({
      nodes,
      onNodeClick,
    }: {
      nodes: FlowNode[];
      onNodeClick: (event: unknown, node: FlowNode) => void;
    }) => (
      <div data-testid="canvas">
        {nodes.map((node) => (
          <button
            key={node.id}
            type="button"
            data-node={node.id}
            onClick={(event) => onNodeClick(event, node)}
          >
            {node.id}
          </button>
        ))}
      </div>
    ),
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Background: () => null,
    useReactFlow: () => flow,
    addEdge: (_e: unknown, edges: unknown) => edges,
    applyEdgeChanges: (_c: unknown, edges: unknown) => edges,
    applyNodeChanges: (_c: unknown, nodes: unknown) => nodes,
  };
});
vi.mock('reactflow/dist/style.css', () => ({}));

// The leave confirm, drawn as its message while it is open.
vi.mock('../../modals/ConfirmationModal', () => ({
  default: ({
    message,
    modalState,
  }: {
    message: string;
    modalState: string;
  }) =>
    modalState === 'ACTIVE' ? <p data-testid="confirm">{message}</p> : null,
}));
vi.mock('../../modals/AgentDetailsModal', () => ({ default: () => null }));
vi.mock('../../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../components/AgentPreviewSheet', () => ({ default: () => null }));
vi.mock('./WorkflowPreview', () => ({ default: () => null }));
vi.mock('./NodePalette', () => ({
  default: ({ onAdd }: { onAdd: (type: string) => void }) => (
    <button type="button" data-add="agent" onClick={() => onAdd('agent')}>
      add agent
    </button>
  ),
}));
vi.mock('./CanvasControls', () => ({ default: () => null }));
vi.mock('./panels/NodePanel', () => ({
  default: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="node-panel">{children}</div>
  ),
}));
const panel = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));
// The node's Tools picker footer, as its Go to Tools link.
vi.mock('./panels/AgentPanel', () => ({
  default: (props: Record<string, unknown>) => {
    panel.props = props;
    return (
      <a
        href="/settings/tools"
        data-testid="go-to-tools"
        onClick={(event) => {
          (props.onNavigateAway as (e: unknown) => void)?.(event);
          if (!event.defaultPrevented) event.preventDefault();
        }}
      >
        go
      </a>
    );
  },
}));
const sheet = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));
vi.mock('./components/WorkflowDetailsSheet', () => ({
  default: (props: Record<string, unknown>) => {
    sheet.props = props;
    return null;
  },
}));

const ok = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

const AGENT = {
  id: 'a1',
  name: 'Renewal desk',
  agent_type: 'workflow',
  workflow: 'w1',
  allowed_actions: ['view', 'edit', 'publish', 'delete'],
  config: {},
};
const workflowWith = (agentData: Record<string, unknown>) => ({
  workflow: { name: 'Renewal desk', description: '' },
  nodes: [
    { id: 'start', type: 'start', title: 'Start', position: { x: 0, y: 0 } },
    {
      id: 'agent',
      type: 'agent',
      title: 'Agent',
      position: { x: 0, y: 100 },
      data: agentData,
    },
    { id: 'end', type: 'end', title: 'End', position: { x: 0, y: 200 } },
  ],
  edges: [
    { id: 'e1', source: 'start', target: 'agent' },
    { id: 'e2', source: 'agent', target: 'end' },
  ],
});
const api = vi.hoisted(() => ({
  workflow: null as unknown,
  tools: [] as unknown[],
  updateAgent: vi.fn(),
  updateWorkflow: vi.fn(),
}));
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: () => ok(AGENT),
    updateAgent: (...a: unknown[]) => api.updateAgent(...a),
    updateWorkflow: (...a: unknown[]) => api.updateWorkflow(...a),
    getUserTools: () => ok({ tools: api.tools }),
    getWorkflow: () => ok({ success: true, data: api.workflow }),
  },
}));
const MODEL = {
  id: 'm1',
  value: 'm1',
  provider: 'openai',
  display_name: 'Model one',
  context_window: 128000,
  supported_attachment_types: [],
  supports_tools: true,
  supports_structured_output: true,
  supports_streaming: true,
};
vi.mock('../../api/services/modelService', () => ({
  default: {
    getModels: () => ok({ models: [MODEL], default_model_id: 'm1' }),
    transformModels: (models: unknown[]) => models,
  },
}));

import WorkflowBuilder from './WorkflowBuilder';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('WorkflowBuilder canvas', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    api.workflow = workflowWith({
      model_id: 'm1',
      llm_name: 'openai',
      prompt_template: 'Hi',
    });
    api.tools = [];
    api.updateAgent.mockReset().mockImplementation(() => ok({ id: 'a1' }));
    api.updateWorkflow
      .mockReset()
      .mockImplementation(() => ok({ success: true }));
    panel.props = null;
    sheet.props = null;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (path = '/agents/workflow/edit/a1') => {
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/agents/workflow/edit/:agentId"
              element={<WorkflowBuilder />}
            />
            <Route
              path="/agents/manage/workflow/new"
              element={<WorkflowBuilder />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
    await act(async () => undefined);
  };

  const nodeButton = (id: string) =>
    container.querySelector<HTMLButtonElement>(`[data-node="${id}"]`);
  const select = async (id: string) => act(async () => nodeButton(id)!.click());
  const press = async (target: EventTarget, init: KeyboardEventInit) =>
    act(async () => {
      target.dispatchEvent(
        new KeyboardEvent('keydown', { bubbles: true, ...init }),
      );
    });

  describe('shortcuts', () => {
    // A modal or popover over the canvas (Add tool, a picker) owns its keys:
    // Backspace on one of its buttons must not delete the selected node.
    it.each([['dialog'], ['alertdialog'], ['listbox'], ['menu']])(
      'ignores Delete, Backspace and undo from inside a %s',
      async (role) => {
        await render();
        await select('end');
        const layer = document.createElement('div');
        layer.setAttribute('role', role);
        const button = document.createElement('button');
        layer.appendChild(button);
        document.body.appendChild(layer);

        await press(button, { key: 'Backspace' });
        await press(button, { key: 'Delete' });
        expect(nodeButton('end')).not.toBeNull();

        // The canvas itself still deletes and undoes.
        await press(document.body, { key: 'Backspace' });
        expect(nodeButton('end')).toBeNull();
        await press(button, { key: 'z', ctrlKey: true });
        expect(nodeButton('end')).toBeNull();
        await press(document.body, { key: 'z', ctrlKey: true });
        expect(nodeButton('end')).not.toBeNull();
      },
    );
  });

  describe('a node without a model', () => {
    beforeEach(() => {
      api.workflow = workflowWith({ prompt_template: 'Hi' });
    });

    it('gets the default model on select without marking the workflow changed', async () => {
      await render();
      expect(container.textContent).not.toContain(
        'agents.workflow.builder.unsavedChanges',
      );
      await select('agent');
      const node = panel.props!.node as {
        data: { config: Record<string, unknown> };
      };
      expect(node.data.config.model_id).toBe('m1');
      expect(container.textContent).not.toContain(
        'agents.workflow.builder.unsavedChanges',
      );
      const saveButton = [...container.querySelectorAll('button')].find(
        (button) => button.textContent === 'agents.form.buttons.save',
      );
      expect(saveButton?.disabled).toBe(true);
    });

    it('saves the filled model and stays saved afterwards', async () => {
      await render();
      await select('agent');
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: 'Answers renewals',
          allowPromptOverride: false,
          imageFile: null,
        }),
      );
      await act(async () => undefined);
      const sent = api.updateWorkflow.mock.calls.at(-1)![1] as {
        nodes: { id: string; data: Record<string, unknown> }[];
      };
      expect(sent.nodes.find((n) => n.id === 'agent')!.data.model_id).toBe(
        'm1',
      );
      expect(container.textContent).not.toContain(
        'agents.workflow.builder.unsavedChanges',
      );
    });
  });

  describe('the description', () => {
    const saveWith = async (description: string) => {
      await render();
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description,
          allowPromptOverride: false,
          imageFile: null,
        }),
      );
      await act(async () => undefined);
      return api.updateAgent.mock.calls.at(-1)![1] as FormData;
    };

    it('sends what the user typed', async () => {
      const form = await saveWith('Answers renewals');
      expect(form.get('description')).toBe('Answers renewals');
    });

    // The server refuses an empty description on update, and a made-up
    // English one is not what the user typed: a blank one is left out.
    it('sends no made-up description when it is blank', async () => {
      const form = await saveWith('');
      expect(form.get('description')).toBeNull();
    });
  });

  describe('the node Tools picker', () => {
    it('offers the tools a node can run, workflow-only ones included', async () => {
      api.tools = [
        { id: 'own', name: 'brave' },
        {
          id: 'doc',
          name: 'read_document',
          builtin: true,
          workflow_only: true,
        },
        { id: 'job', name: 'check_job', builtin: true },
        {
          id: 'shared',
          name: 'brave',
          access: 'viewer',
          allowed_actions: ['use'],
        },
      ];
      await render();
      await select('agent');
      const tools = panel.props!.availableTools as { id: string }[];
      expect(tools.map((tool) => tool.id)).toEqual(['own', 'doc']);
    });
  });

  describe('unsaved changes', () => {
    const NEW = '/agents/manage/workflow/new';
    const unsaved = () =>
      container.textContent?.includes('agents.workflow.builder.unsavedChanges');
    const goToTools = async () =>
      act(async () =>
        container
          .querySelector<HTMLAnchorElement>('[data-testid="go-to-tools"]')!
          .click(),
      );
    const asked = () =>
      container.querySelector('[data-testid="confirm"]')?.textContent ===
      'agents.form.leave.title';
    const addAgent = async () =>
      act(async () =>
        container
          .querySelector<HTMLButtonElement>('[data-add="agent"]')!
          .click(),
      );
    const agentNodeId = () =>
      [...container.querySelectorAll<HTMLElement>('[data-node]')]
        .map((el) => el.dataset.node!)
        .find((id) => id.startsWith('agent'))!;

    it('reads an untouched new workflow as saved', async () => {
      await render(NEW);
      expect(unsaved()).toBe(false);
    });

    it('asks before a new workflow with work on it is left', async () => {
      await render(NEW);
      await addAgent();
      expect(unsaved()).toBe(true);
      await select(agentNodeId());
      await goToTools();
      expect(asked()).toBe(true);
    });

    it('asks while a saved workflow has an edit, and not after it is saved', async () => {
      await render();
      await select('agent');
      await goToTools();
      expect(asked()).toBe(false);

      const onUpdate = panel.props!.onUpdate as (data: object) => void;
      const node = panel.props!.node as { data: { config: object } };
      await act(async () =>
        onUpdate({ config: { ...node.data.config, prompt_template: 'Bye' } }),
      );
      await goToTools();
      expect(asked()).toBe(true);

      await render();
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: '',
          allowPromptOverride: false,
          imageFile: null,
        }),
      );
      await act(async () => undefined);
      expect(unsaved()).toBe(false);
    });
  });
});
