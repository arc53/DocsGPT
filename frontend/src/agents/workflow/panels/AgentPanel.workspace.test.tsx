import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import type { Node } from 'reactflow';

import type { Doc } from '../../../models/misc';
import type { UserTool } from '../workflowHelpers';

vi.mock('../../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useDarkTheme: () => [false, () => undefined],
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const store = vi.hoisted(() => ({ state: {} as Record<string, unknown> }));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
  useDispatch: () => () => undefined,
}));
vi.mock('../../../upload/Upload', () => ({ default: () => null }));
vi.mock('../../../modals/AddToolModal', () => ({ default: () => null }));
vi.mock('../../../api/services/devicesService', () => ({
  default: { list: async () => ({ devices: [] }) },
}));
vi.mock('../components/PromptTextArea', () => ({
  default: () => null,
  extractUpstreamVariables: () => [],
}));
vi.mock('../components/NodeDocumentsControl', () => ({ default: () => null }));

import AgentPanel from './AgentPanel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const personal = { kind: 'personal' as const, team_id: null };
const team = { kind: 'team' as const, team_id: 't1' };

type Workspace = typeof personal | typeof team;
const doc = (
  id: string,
  workspace: Workspace,
  folderId: string | null = null,
): Doc =>
  ({
    id,
    name: `Doc ${id}`,
    date: '2026-10-01',
    model: 'm',
    folder_id: folderId,
    workspace,
  }) as Doc;
const tool = (
  id: string,
  workspace: Workspace,
  folderId: string | null = null,
): UserTool =>
  ({
    id,
    name: 'memory',
    displayName: `Tool ${id}`,
    workspace,
    folder_id: folderId,
  }) as UserTool;

const node: Node = {
  id: 'agent_1',
  type: 'agent',
  position: { x: 0, y: 0 },
  data: { config: { sources: [], tools: [] } },
};

describe('AgentPanel pickers in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    store.state = {
      workspace: { current: 't1' },
      preference: {
        token: 'tok',
        sourceDocs: [
          doc('mine', personal),
          doc('loose', team),
          doc('filed', team, 'f1'),
        ],
      },
      connectors: { connections: [], catalog: [], loaded: true },
      folders: {
        tree: {
          items: [
            {
              id: 'f1',
              name: 'Carriers',
              parent_id: null,
              counts: { source: 1 },
            },
          ],
          loaded: true,
          loading: false,
          failed: false,
          latestRequestId: null,
          removedParents: {},
        },
      },
    };
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = (holderWorkspace: Workspace = team) =>
    act(async () =>
      root.render(
        <MemoryRouter>
          <AgentPanel
            node={node}
            onUpdate={vi.fn()}
            nodes={[node]}
            edges={[]}
            availableModels={[]}
            availableTools={[
              tool('my-tool', personal),
              tool('our-tool', team),
              tool('filed-tool', team, 'f1'),
            ]}
            documentOptions={[]}
            jsonSchemaText=""
            jsonSchemaError={null}
            modelSupportsStructuredOutput
            onJsonSchemaChange={vi.fn()}
            onReloadTools={async () => []}
            holderWorkspace={holderWorkspace}
            holderFolderId="f1"
          />
        </MemoryRouter>,
      ),
    );

  const triggers = () =>
    Array.from(container.querySelectorAll<HTMLElement>('[role="combobox"]'));
  const open = (trigger: HTMLElement) =>
    act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  const popoverRows = () =>
    Array.from(
      document.querySelectorAll<HTMLElement>(
        '[data-slot="popover-content"] [data-slot="command-item"]',
      ),
    ).map((row) => row.getAttribute('data-value'));
  const headings = () =>
    Array.from(
      document.querySelectorAll(
        '[data-slot="popover-content"] [cmdk-group-heading]',
      ),
    ).map((el) => el.textContent);

  it("lists the workflow's folder first and nothing of another workspace", async () => {
    await render();
    const [sources] = triggers().filter((el) =>
      el.textContent?.includes('selectSources'),
    );
    await open(sources);
    expect(headings()[0]).toBe('workspace.pickers.inWorkflowFolder');
    expect(popoverRows()).toEqual([
      'Doc filed filed',
      'Carriers folder:f1',
      'Doc loose loose',
    ]);
  });

  it("lists the workflow's folder first among the tools", async () => {
    await render();
    const [tools] = triggers().filter((el) =>
      el.textContent?.includes('selectTools'),
    );
    await open(tools);
    expect(headings()[0]).toBe('workspace.pickers.inWorkflowFolder');
    expect(popoverRows()).toEqual([
      'Tool filed-tool filed-tool',
      'Tool our-tool our-tool',
    ]);
  });

  it("lists nothing of the team's for a workflow that lives elsewhere", async () => {
    await render(personal);
    const [sources] = triggers().filter((el) =>
      el.textContent?.includes('selectSources'),
    );
    await open(sources);
    expect(popoverRows()).toEqual([]);
  });
});
