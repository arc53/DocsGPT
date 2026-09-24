import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const copyMock = vi.fn<(text: string) => boolean>(() => true);
vi.mock('copy-to-clipboard', () => ({
  default: (text: string) => copyMock(text),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import CopyButton from './CopyButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CopyButton', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    vi.useFakeTimers();
    copyMock.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  function button(): HTMLButtonElement {
    const el = container.querySelector('button');
    if (!el) throw new Error('no button');
    return el;
  }

  async function click() {
    await act(async () => {
      button().click();
    });
  }

  it('renders an idle ghost-muted icon button', () => {
    act(() => root.render(<CopyButton textToCopy="hello" />));
    expect(button().getAttribute('aria-label')).toBe('conversation.copy');
    expect(button().dataset.variant).toBe('ghost-muted');
    expect(button().dataset.size).toBe('icon-sm');
    expect(button().dataset.shape).toBe('pill');
  });

  it('uses icon-xs when size is xs and xs with text', () => {
    act(() => root.render(<CopyButton textToCopy="hello" size="xs" />));
    expect(button().dataset.size).toBe('icon-xs');
    act(() => root.render(<CopyButton textToCopy="hello" showText />));
    expect(button().dataset.size).toBe('xs');
    expect(button().textContent).toContain('conversation.copy');
  });

  it('copies the text and shows the copied state without disabling', async () => {
    act(() => root.render(<CopyButton textToCopy="hello" showText />));
    await click();

    expect(copyMock).toHaveBeenCalledWith('hello');
    expect(button().getAttribute('aria-label')).toBe('conversation.copied');
    expect(button().dataset.variant).toBe('secondary');
    expect(button().hasAttribute('disabled')).toBe(false);
    expect(button().textContent).toContain('conversation.copied');
  });

  it('ignores clicks while copied and resets after the timeout', async () => {
    act(() =>
      root.render(<CopyButton textToCopy="hello" copiedDuration={1000} />),
    );
    await click();
    await click();
    expect(copyMock).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(button().getAttribute('aria-label')).toBe('conversation.copy');
    expect(button().dataset.variant).toBe('ghost-muted');
  });
});
