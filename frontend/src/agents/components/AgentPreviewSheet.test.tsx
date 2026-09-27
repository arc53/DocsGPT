import { act } from 'react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const dispatch = vi.fn();
vi.mock('react-redux', () => ({ useDispatch: () => dispatch }));
import { createRoot, type Root } from 'react-dom/client';

import AgentPreviewSheet from './AgentPreviewSheet';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentPreviewSheet', () => {
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

  const render = async () => {
    await act(async () => {
      root.render(
        <AgentPreviewSheet
          open
          onOpenChange={() => undefined}
          title="Preview"
          description="Carrier onboarding FAQ"
          actions={<span data-testid="action">Running</span>}
        >
          <div data-testid="body">Chat</div>
        </AgentPreviewSheet>,
      );
    });
  };

  it('is a right Sheet at the workflow preview widths', async () => {
    await render();
    const content = document.querySelector<HTMLElement>(
      '[data-slot="sheet-content"]',
    )!;
    expect(content.dataset.side).toBe('right');
    expect(content.className).toContain('lg:max-w-[800px]');
    expect(content.className).toContain('p-0');
  });

  it('titles the drawer with SheetTitle and SheetDescription', async () => {
    await render();
    expect(
      document.querySelector('[data-slot="sheet-title"]')?.textContent,
    ).toBe('Preview');
    expect(
      document.querySelector('[data-slot="sheet-description"]')?.textContent,
    ).toBe('Carrier onboarding FAQ');
  });

  it('keeps header actions clear of the close button', async () => {
    await render();
    const action = document.querySelector('[data-testid="action"]')!;
    const header = action.parentElement!;
    // The X sits at top-2 right-2 (32px wide); pr-12 keeps 48px free.
    expect(header.className).toContain('pr-12');
    expect(
      header.contains(document.querySelector('[data-slot="sheet-title"]')),
    ).toBe(true);
  });

  // DESIGN maps "running" to info, as schedule runs do (was primary text).
  it('shows a running run as an info badge in the header', async () => {
    await act(async () => {
      root.render(
        <AgentPreviewSheet
          open
          onOpenChange={() => undefined}
          title="Preview"
          running
        >
          <div />
        </AgentPreviewSheet>,
      );
    });
    const badge = document.querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(badge.dataset.variant).toBe('info');
    expect(badge.textContent).toBe('agents.schedules.status.running');
  });

  // The toast stack moves bottom-left while any agent preview is open.
  it('reports whether it is open, and closed when it goes away', async () => {
    dispatch.mockClear();
    await render();
    expect(dispatch).toHaveBeenCalledWith({
      type: 'workflowPreview/setPreviewOpen',
      payload: true,
    });
    await act(async () => root.unmount());
    root = createRoot(container);
    expect(dispatch).toHaveBeenLastCalledWith({
      type: 'workflowPreview/setPreviewOpen',
      payload: false,
    });
  });

  it('renders the body under a separator on the sheet surface', async () => {
    await render();
    const body = document.querySelector('[data-testid="body"]')!;
    expect(body.textContent).toBe('Chat');
    expect(document.querySelector('[data-slot="separator"]')).not.toBeNull();
    const content = document.querySelector('[data-slot="sheet-content"]')!;
    expect(content.querySelector('.bg-card')).toBeNull();
  });
});
