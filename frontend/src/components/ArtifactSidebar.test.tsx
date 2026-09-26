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
}));

const documentMock = vi.fn();
const legacyMock = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getDocumentArtifact: (...args: unknown[]) => documentMock(...args),
    getArtifact: (...args: unknown[]) => legacyMock(...args),
  },
}));

import ArtifactSidebar from './ArtifactSidebar';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ArtifactSidebar', () => {
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

  it('shows a failed load as an alert with Retry that refetches', async () => {
    documentMock.mockResolvedValue({ ok: false, status: 500 });
    legacyMock.mockRejectedValue(new Error('offline'));

    await act(async () => {
      root.render(
        <ArtifactSidebar
          isOpen
          onClose={vi.fn()}
          artifactId="a1"
          conversationId="c1"
          variant="split"
        />,
      );
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('components.artifact.fetchFailed');
    expect(documentMock).toHaveBeenCalledTimes(1);

    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );
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
        <ArtifactSidebar
          isOpen
          onClose={vi.fn()}
          artifactId="a2"
          conversationId="c1"
          variant="split"
        />,
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
