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
// The sponsor confirmation, as a button that agrees.
vi.mock('../components/SponsorConfirmModal', () => ({
  default: ({
    confirmation,
    onConfirm,
  }: {
    confirmation: { resources: { key: string }[] } | null;
    onConfirm: (keys: string[]) => void;
  }) =>
    confirmation ? (
      <button
        type="button"
        data-testid="confirm-sponsor"
        onClick={() => onConfirm(confirmation.resources.map((r) => r.key))}
      />
    ) : null,
}));
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
  agentStatus: undefined as string | undefined,
  agentExtra: {} as Record<string, unknown>,
  getWorkflow: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  updateWorkflow: vi.fn(),
}));
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: () =>
      ok({
        ...AGENT,
        ...(api.agentStatus ? { status: api.agentStatus } : {}),
        ...api.agentExtra,
      }),
    createAgent: (...a: unknown[]) => api.createAgent(...a),
    updateAgent: (...a: unknown[]) => api.updateAgent(...a),
    updateWorkflow: (...a: unknown[]) => api.updateWorkflow(...a),
    getUserTools: () => ok({ tools: api.tools }),
    getWorkflow: (...a: unknown[]) => api.getWorkflow(...a),
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
    api.agentStatus = undefined;
    api.agentExtra = {};
    api.getWorkflow
      .mockReset()
      .mockImplementation(() => ok({ success: true, data: api.workflow }));
    api.createAgent.mockReset();
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

    // Older nodes carry a provider, or an empty model, before the prompt.
    it.each([
      [{ llm_name: 'openai', prompt_template: 'Hi' }],
      [{ model_id: null, prompt_template: 'Hi' }],
      [{ model_id: '', llm_name: '', prompt_template: 'Hi' }],
    ])(
      'reads an older node %j as unchanged once selected',
      async (agentData) => {
        api.workflow = workflowWith(agentData);
        await render();
        await select('agent');
        const node = panel.props!.node as {
          data: { config: Record<string, unknown> };
        };
        expect(node.data.config.model_id).toBe('m1');
        expect(container.textContent).not.toContain(
          'agents.workflow.builder.unsavedChanges',
        );
        await act(async () =>
          container
            .querySelector<HTMLAnchorElement>('[data-testid="go-to-tools"]')!
            .click(),
        );
        expect(container.querySelector('[data-testid="confirm"]')).toBeNull();
      },
    );

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
      const form = api.updateAgent.mock.calls.at(-1)![1] as FormData;
      const sent = JSON.parse(form.get('workflow_graph') as string) as {
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

    // A made-up English one is not what the user typed; a workflow
    // agent's description may be blank, so clearing it saves.
    it('sends a blank description as blank', async () => {
      const form = await saveWith('');
      expect(form.get('description')).toBe('');
    });
  });

  describe('a refused save', () => {
    const saveAndRead = async (status: number, body: unknown) => {
      api.updateAgent.mockImplementation(
        async () =>
          new Response(JSON.stringify(body), {
            status,
            headers: { 'Content-Type': 'application/json' },
          }),
      );
      await render();
      const onOpenChange = sheet.props!.onOpenChange as (o: boolean) => void;
      await act(async () => onOpenChange(true));
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
      return sheet.props!.errors as string[];
    };

    it('says what the caller may not run with their access', async () => {
      const errors = await saveAndRead(403, {
        code: 'sponsor_not_allowed',
        resources: [{ key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' }],
      });
      expect(errors).toEqual(['agents.form.sponsors.notAllowed']);
    });

    it('says a confirmation is outdated', async () => {
      const errors = await saveAndRead(400, {
        code: 'sponsor_confirmation_unexpected',
      });
      expect(errors).toEqual(['agents.form.sponsors.confirmationOutdated']);
    });

    it("gives the server's own message", async () => {
      const errors = await saveAndRead(400, { message: 'Bad graph' });
      expect(errors).toEqual(['Bad graph']);
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

  describe('drafts and the one-request save', () => {
    const NEW = '/agents/manage/workflow/new';
    const json = (status: number, body: unknown) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      });
    const button = (label: string) =>
      [...container.querySelectorAll('button')].find(
        (b) => b.textContent === label,
      );
    const unsaved = () =>
      container.textContent?.includes('agents.workflow.builder.unsavedChanges');
    const graphOf = (form: FormData) =>
      JSON.parse(form.get('workflow_graph') as string) as {
        nodes: { id: string; type: string }[];
        edges: unknown[];
        retry_defaults: unknown;
      };

    it('saves a new, unfinished workflow as a draft in one request', async () => {
      const sent: Record<string, unknown>[] = [];
      api.createAgent.mockImplementation(async (form: FormData) => {
        sent.push(Object.fromEntries(form.entries()));
        return json(201, { id: 'a9', key: '', image: '', workflow_id: 'w9' });
      });
      await render(NEW);
      // A draft: no Published badge, and Save draft beside Publish.
      expect(container.textContent).toContain('agents.card.draft');
      await act(async () =>
        container
          .querySelector<HTMLButtonElement>('[data-add="agent"]')!
          .click(),
      );
      expect(unsaved()).toBe(true);
      await act(async () => button('agents.form.buttons.saveDraft')!.click());
      await act(async () => undefined);
      expect(api.createAgent).toHaveBeenCalledTimes(1);
      expect(api.updateWorkflow).not.toHaveBeenCalled();
      expect(sent[0]).toMatchObject({
        name: 'New Workflow',
        description: '',
        status: 'draft',
        agent_type: 'workflow',
      });
      const graph = JSON.parse(sent[0].workflow_graph as string);
      // No end node yet: a draft saves it anyway.
      expect(graph.nodes.map((n: { type: string }) => n.type)).toEqual([
        'start',
        'agent',
      ]);
      expect(graph.retry_defaults).toBeNull();
      // Saved: the leave guard starts over, and it is still a draft.
      expect(unsaved()).toBe(false);
      expect(container.textContent).toContain('agents.card.draft');
      expect(button('agents.form.buttons.publish')).toBeDefined();
    });

    it('asks before a new workflow runs something with the caller access, then creates it', async () => {
      const confirms: (string | null)[] = [];
      api.createAgent.mockImplementation(async (form: FormData) => {
        confirms.push(form.get('confirm_sponsor') as string | null);
        return confirms.length === 1
          ? json(409, {
              code: 'sponsor_confirmation_required',
              resources: [
                { key: 'tool:t1', type: 'tool', id: 't1', name: 'Jira' },
              ],
              audience: {
                teams: [],
                api_key: false,
                public_link: false,
                webhook: false,
              },
            })
          : json(201, { id: 'a9', key: '', image: '', workflow_id: 'w9' });
      });
      await render(NEW);
      await act(async () => button('agents.form.buttons.saveDraft')!.click());
      await act(async () =>
        container
          .querySelector<HTMLButtonElement>('[data-testid="confirm-sponsor"]')!
          .click(),
      );
      await act(async () => undefined);
      expect(confirms).toEqual([null, JSON.stringify(['tool:t1'])]);
      expect(unsaved()).toBe(false);
    });

    it('publishes a draft without another change, in one request', async () => {
      api.agentStatus = 'draft';
      api.updateAgent.mockImplementation(async () =>
        json(200, { success: true, id: 'a1', workflow_id: 'w1', key: 'k' }),
      );
      await render();
      expect(container.textContent).toContain('agents.card.draft');
      expect(button('agents.form.buttons.saveDraft')).toBeDefined();
      const publish = button('agents.form.buttons.publish')!;
      expect(publish.disabled).toBe(false);
      await act(async () => publish.click());
      await act(async () => undefined);
      const form = api.updateAgent.mock.calls.at(-1)![1] as FormData;
      expect(form.get('status')).toBe('published');
      expect(graphOf(form).nodes.map((n) => n.id)).toEqual([
        'start',
        'agent',
        'end',
      ]);
      expect(api.updateWorkflow).not.toHaveBeenCalled();
      expect(container.textContent).toContain('agents.form.status.published');
      expect(button('agents.form.buttons.saveDraft')).toBeUndefined();
      expect(button('agents.form.buttons.save')!.disabled).toBe(true);
    });

    it('lists each problem the server finds in the graph', async () => {
      api.agentStatus = 'draft';
      api.updateAgent.mockImplementation(async () =>
        json(400, {
          success: false,
          message: 'Workflow validation failed',
          error: 'Workflow validation failed',
          errors: ['Agent node needs a model', 'End is unreachable'],
        }),
      );
      await render();
      await act(async () => button('agents.form.buttons.publish')!.click());
      await act(async () => undefined);
      const alert = container.querySelector('[role="alert"]')!;
      expect(alert.textContent).toContain(
        'agents.workflow.builder.unablePublish',
      );
      expect(alert.textContent).toContain('Agent node needs a model');
      expect(alert.textContent).toContain('End is unreachable');
      expect(alert.textContent).not.toContain('Workflow validation failed');
      expect(container.textContent).toContain('agents.card.draft');
    });

    // The schema text that doesn't parse lives only in the panel: a draft
    // save would send the last valid one and lose the edit.
    it('refuses a draft save while an output schema is unfinished, and counts it as unsaved', async () => {
      api.agentStatus = 'draft';
      await render();
      await select('agent');
      const onSchema = panel.props!.onJsonSchemaChange as (
        text: string,
      ) => void;
      await act(async () => onSchema('{ "type": '));
      expect(unsaved()).toBe(true);
      await act(async () =>
        container
          .querySelector<HTMLAnchorElement>('[data-testid="go-to-tools"]')!
          .click(),
      );
      expect(container.querySelector('[data-testid="confirm"]')).not.toBeNull();

      await act(async () => button('agents.form.buttons.saveDraft')!.click());
      await act(async () => undefined);
      expect(api.updateAgent).not.toHaveBeenCalled();
      expect(container.querySelector('[role="alert"]')!.textContent).toContain(
        'agents.workflow.validation.agentSchema',
      );

      // Back to what the node holds: nothing unsaved.
      await act(async () => onSchema(''));
      expect(unsaved()).toBe(false);
    });

    it('keeps a draft a draft when its details are saved', async () => {
      api.agentStatus = 'draft';
      await render();
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: 'x',
          allowPromptOverride: false,
          imageFile: null,
        }),
      );
      await act(async () => undefined);
      const form = api.updateAgent.mock.calls.at(-1)![1] as FormData;
      expect(form.get('status')).toBe('draft');
    });
  });

  describe('while the saved graph loads', () => {
    const button = (label: string) =>
      [...container.querySelectorAll('button')].find(
        (b) => b.textContent === label,
      );
    const saveDetails = async () => {
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
    };

    // A save before the graph arrives would store an empty graph over it.
    it('saves nothing until the graph has loaded', async () => {
      api.agentStatus = 'draft';
      let finish: (value: unknown) => void = () => undefined;
      api.getWorkflow.mockImplementation(
        () =>
          new Promise((resolve) => {
            finish = resolve;
          }),
      );
      await render();
      expect(button('agents.form.buttons.saveDraft')!.disabled).toBe(true);
      expect(button('agents.form.buttons.publish')!.disabled).toBe(true);
      await act(async () => button('agents.form.buttons.saveDraft')!.click());
      await saveDetails();
      expect(api.updateAgent).not.toHaveBeenCalled();
      await act(async () =>
        finish({
          ok: true,
          json: () => Promise.resolve({ success: true, data: api.workflow }),
        }),
      );
      await act(async () => undefined);
      expect(button('agents.form.buttons.saveDraft')!.disabled).toBe(false);
    });

    it('shows a failed load with Retry instead of an empty canvas, and never saves it', async () => {
      api.agentStatus = 'draft';
      api.getWorkflow.mockImplementation(() =>
        Promise.resolve({ ok: false, json: () => Promise.resolve({}) }),
      );
      await render();
      const alert = container.querySelector('[role="alert"]');
      expect(alert?.textContent).toContain(
        'agents.workflow.builder.loadFailedTitle',
      );
      expect(container.querySelector('[data-testid="canvas"]')).toBeNull();
      expect(button('agents.form.buttons.saveDraft')!.disabled).toBe(true);
      await saveDetails();
      expect(api.updateAgent).not.toHaveBeenCalled();

      api.getWorkflow.mockImplementation(() =>
        ok({ success: true, data: api.workflow }),
      );
      await act(async () => button('retry')!.click());
      await act(async () => undefined);
      expect(container.querySelector('[data-testid="canvas"]')).not.toBeNull();
      expect(nodeButton('end')).not.toBeNull();
      expect(button('agents.form.buttons.saveDraft')!.disabled).toBe(false);
    });

    // An older workflow agent kept a made-up description on the agent and
    // none on its workflow: the agent's fields are what the builder shows
    // and saves, so it opens clean.
    it("opens clean on the agent's own name and description", async () => {
      api.agentExtra = { description: 'Workflow agent: Renewal desk' };
      api.workflow = {
        ...workflowWith({ model_id: 'm1', llm_name: 'openai' }),
        workflow: { name: 'Old name', description: '' },
      };
      await render();
      expect(
        container.textContent?.includes(
          'agents.workflow.builder.unsavedChanges',
        ),
      ).toBe(false);
      expect(
        (sheet.props!.details as { description: string }).description,
      ).toBe('Workflow agent: Renewal desk');
      expect((sheet.props!.details as { name: string }).name).toBe(
        'Renewal desk',
      );
    });

    // The graph just saved is the one on the canvas: reading it back would
    // drop the undo history and edits made while the save was out.
    it('does not read back the graph a first save just wrote', async () => {
      api.createAgent.mockImplementation(
        async () =>
          new Response(
            JSON.stringify({ id: 'a9', key: '', image: '', workflow_id: 'w9' }),
            { status: 201, headers: { 'Content-Type': 'application/json' } },
          ),
      );
      await render('/agents/manage/workflow/new');
      await act(async () =>
        container
          .querySelector<HTMLButtonElement>('[data-add="agent"]')!
          .click(),
      );
      await act(async () => button('agents.form.buttons.saveDraft')!.click());
      await act(async () => undefined);
      expect(api.createAgent).toHaveBeenCalledTimes(1);
      // The canvas is what was built, not the fixture's saved graph.
      expect(nodeButton('end')).toBeNull();
    });
  });

  describe("a team editor's stale save", () => {
    const saveDetails = async () => {
      const onSave = sheet.props!.onSave as (values: object) => void;
      await act(async () =>
        onSave({
          name: 'Renewal desk',
          description: 'x',
          allowPromptOverride: false,
          imageFile: null,
        }),
      );
      await act(async () => undefined);
    };

    it('sends the stamp it loaded, then the one each save answered with', async () => {
      api.agentExtra = { updated_at: 'stamp-1' };
      api.updateAgent.mockImplementation(
        async () =>
          new Response(
            JSON.stringify({ success: true, id: 'a1', updated_at: 'stamp-2' }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
      );
      await render();
      await saveDetails();
      const first = api.updateAgent.mock.calls.at(-1)![1] as FormData;
      expect(first.get('expected_updated_at')).toBe('stamp-1');
      await saveDetails();
      const second = api.updateAgent.mock.calls.at(-1)![1] as FormData;
      expect(second.get('expected_updated_at')).toBe('stamp-2');
    });

    it('says someone else saved and keeps the canvas', async () => {
      api.agentExtra = { updated_at: 'stamp-1' };
      api.updateAgent.mockImplementation(
        async () =>
          new Response(
            JSON.stringify({
              success: false,
              message: 'Agent was modified by someone else',
              code: 'stale_write',
            }),
            { status: 409, headers: { 'Content-Type': 'application/json' } },
          ),
      );
      await render();
      const onOpenChange = sheet.props!.onOpenChange as (o: boolean) => void;
      await act(async () => onOpenChange(true));
      await saveDetails();
      expect(sheet.props!.errors).toEqual(['agents.form.errors.staleWrite']);
      expect(nodeButton('end')).not.toBeNull();
      expect(
        container.textContent?.includes(
          'agents.workflow.builder.unsavedChanges',
        ),
      ).toBe(true);
    });
  });
});
