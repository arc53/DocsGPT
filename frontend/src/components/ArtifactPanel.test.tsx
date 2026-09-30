import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('react-redux', () => ({
  useSelector: () => null,
}));

vi.mock('../hooks', () => ({
  useDarkTheme: () => [false],
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

const documentMock = vi.fn();
const legacyMock = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getDocumentArtifact: (...args: unknown[]) => documentMock(...args),
    getArtifact: (...args: unknown[]) => legacyMock(...args),
  },
}));

import ArtifactPanel from './ArtifactPanel';
import { SidePanel } from './ui/side-panel';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ArtifactPanel', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    documentMock.mockReset();
    legacyMock.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  // The artifact is the chat's docked side panel: one header with its title,
  // Expand and the one X; the content owns its scroller.
  it('heads the docked panel with its title, Expand and one X', async () => {
    documentMock.mockResolvedValue({ ok: false, status: 500 });
    legacyMock.mockRejectedValue(new Error('offline'));
    await act(async () => {
      root.render(
        <SidePanel
          variant="docked"
          expandable="artifact"
          open
          onOpenChange={vi.fn()}
        >
          <ArtifactPanel artifactId="a1" conversationId="c1" />
        </SidePanel>,
      );
    });
    const header = container.querySelector('[data-slot="panel-header"]')!;
    expect(header.querySelector('h2')?.textContent).toBe(
      'components.artifact.fallbackTitle',
    );
    expect(
      header.querySelectorAll('button[aria-label="sidePanel.close"]'),
    ).toHaveLength(1);
    expect(
      header.querySelector('[aria-label="sidePanel.expand"]'),
    ).not.toBeNull();
    const body = container.querySelector('[data-slot="panel-body"]')!;
    expect(body.className).toContain('overflow-hidden');
  });

  it('shows a failed load as an alert with Retry that refetches', async () => {
    documentMock.mockResolvedValue({ ok: false, status: 500 });
    legacyMock.mockRejectedValue(new Error('offline'));

    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <ArtifactPanel artifactId="a1" conversationId="c1" />
        </SidePanel>,
      );
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('components.artifact.fetchFailed');
    expect(documentMock).toHaveBeenCalledTimes(1);

    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );
    // The shared EmptyState Retry: an outline sm pill.
    expect(retry!.dataset.shape).toBe('pill');
    await act(async () => retry!.click());
    expect(documentMock).toHaveBeenCalledTimes(2);
  });
  // L9: the raw-JSON fallback is a code block in the padded panel, so it is a
  // filled Card around the mono recipe and scrolls inside the panel.
  it('shows an unknown artifact type as a filled Card code block', async () => {
    documentMock.mockResolvedValue({ ok: false, status: 404 });
    legacyMock.mockResolvedValue({
      success: true,
      artifact: { artifact_type: 'mystery', data: { value: 42 } },
    });

    await act(async () => {
      root.render(
        <SidePanel variant="docked" open onOpenChange={vi.fn()}>
          <ArtifactPanel artifactId="a2" conversationId="c1" />
        </SidePanel>,
      );
    });

    const pre = container.querySelector('pre')!;
    expect(pre.textContent).toContain('"mystery"');
    expect(pre.className.split(' ')).toEqual(
      expect.arrayContaining([
        'font-mono',
        'text-xs',
        'whitespace-pre-wrap',
        'wrap-break-word',
      ]),
    );
    const card = pre.parentElement!;
    expect(card.getAttribute('data-slot')).toBe('card');
    expect(card.getAttribute('data-variant')).toBe('filled');
    expect(card.getAttribute('data-padding')).toBe('sm');
  });
});
