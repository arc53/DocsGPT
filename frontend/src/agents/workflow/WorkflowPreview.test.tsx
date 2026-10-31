import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// What every selector reads; the whole preview needs lists, not null.
const redux = vi.hoisted(() => ({
  selected: null as unknown,
  dispatch: vi.fn(),
}));
vi.mock('react-redux', () => ({
  useSelector: () => redux.selected,
  useDispatch: () => redux.dispatch,
}));
vi.mock('../../components/MessageInput', () => ({ default: () => null }));

import WorkflowPreview, { ExecutionDetails } from './WorkflowPreview';
import { addQuery } from './workflowPreviewSlice';
import type { WorkflowNode } from '../types/workflow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const nodes = [
  {
    id: 'n1',
    type: 'agent',
    title: 'Summarise',
    position: { x: 0, y: 0 },
    data: {},
  },
] as unknown as WorkflowNode[];

const steps = [
  {
    nodeId: 'n1',
    nodeType: 'agent',
    nodeTitle: 'Summarise',
    status: 'completed',
    output: 'Three carriers expire this month.',
    stateDelta: { region: 'EU', query: 'ignored' },
  },
] as never;

describe('WorkflowPreview execution sections', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const renderDetails = async (isOpen = true) => {
    await act(async () => {
      root.render(
        <ExecutionDetails
          steps={steps}
          nodes={nodes}
          isOpen={isOpen}
          onToggle={() => undefined}
        />,
      );
    });
  };

  // The answer's step-row recipe (AnswerFlow): ghost sm at ml-3.5, a muted
  // icon, muted text, and a chevron that turns while open.
  it('draws the Execution details toggle as an answer step row', async () => {
    await renderDetails();
    const toggle = container.querySelector<HTMLButtonElement>('button')!;
    expect(toggle.dataset.variant).toBe('ghost');
    expect(toggle.dataset.size).toBe('sm');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(toggle.className).toContain('ml-3.5');
    const icons = toggle.querySelectorAll('svg');
    expect(icons[0].getAttribute('class')).toContain('text-muted-foreground');
    expect(icons[icons.length - 1].getAttribute('class')).toContain(
      'rotate-180',
    );
    expect(toggle.querySelector('p')).toBeNull();
  });

  it('opens the steps in a Collapsible on the answer column', async () => {
    await renderDetails(false);
    const toggle = container.querySelector<HTMLButtonElement>('button')!;
    const body = container.querySelector<HTMLElement>(
      '[data-slot="collapsible"]',
    )!;
    expect(body).not.toBeNull();
    expect(toggle.getAttribute('aria-controls')).toBe(body.id);
    expect(body.dataset.state).toBe('closed');
    expect(body.className).toContain('ml-6');
    await renderDetails(true);
    expect(body.dataset.state).toBe('open');
  });

  it('draws each step as a subtle panel with its output in a filled well', async () => {
    await renderDetails();
    const step = container.querySelector<HTMLElement>(
      '[data-slot="card"][data-variant="subtle"]',
    )!;
    expect(step.dataset.padding).toBe('sm');
    const well = step.querySelector<HTMLElement>(
      '[data-slot="card"][data-variant="filled"]',
    )!;
    expect(well.dataset.padding).toBe('sm');
    expect(well.textContent).toContain('Three carriers expire this month.');
    // No hand-rolled muted boxes: a muted box in a muted box disappears.
    expect(
      container.querySelector(
        'div.bg-muted:not([data-slot="card"]), span.bg-muted',
      ),
    ).toBeNull();
  });

  it('shows state changes as mono neutral badges, without query', async () => {
    await renderDetails();
    const badges = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    );
    expect(badges).toHaveLength(1);
    expect(badges[0].dataset.variant).toBe('neutral');
    expect(badges[0].className).toContain('font-mono');
    expect(badges[0].textContent).toContain('region');
    expect(badges[0].textContent).toContain('EU');
  });
});

describe('WorkflowPreview starters', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    redux.selected = [];
    redux.dispatch.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    redux.selected = null;
  });

  const renderPreview = async (starters?: string[]) => {
    await act(async () => {
      root.render(
        <WorkflowPreview
          workflowData={{ name: 'Renewal desk', nodes, edges: [] }}
          starters={starters}
        />,
      );
    });
  };

  // As the agent preview: the starters under the empty chat, each sending
  // itself.
  it('offers the starters on an empty chat and sends one when picked', async () => {
    await renderPreview(['Which carriers renew this month?']);
    const rows = container.querySelector('[data-testid="hero-suggestions"]');
    expect(rows?.textContent).toContain('Which carriers renew this month?');
    await act(async () =>
      rows!.querySelector<HTMLButtonElement>('button')!.click(),
    );
    expect(redux.dispatch).toHaveBeenCalledWith(
      addQuery({ prompt: 'Which carriers renew this month?' }),
    );
  });

  it('shows only the empty state without starters', async () => {
    await renderPreview([]);
    expect(
      container.querySelector('[data-testid="hero-suggestions"]'),
    ).toBeNull();
    expect(container.textContent).toContain(
      'agents.workflow.preview.emptyTitle',
    );
  });
});
