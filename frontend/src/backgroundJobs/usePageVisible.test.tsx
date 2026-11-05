import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { usePageAttended } from './usePageVisible';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let attended: boolean | null = null;
function Probe() {
  attended = usePageAttended();
  return null;
}

describe('usePageAttended', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    vi.useFakeTimers();
    vi.spyOn(document, 'hasFocus').mockReturnValue(true);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Probe />));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('follows the window losing and regaining focus', async () => {
    const focused = vi.mocked(document.hasFocus);
    expect(attended).toBe(true);
    focused.mockReturnValue(false);
    await act(async () => {
      window.dispatchEvent(new Event('blur'));
      vi.advanceTimersByTime(0);
    });
    expect(attended).toBe(false);
    focused.mockReturnValue(true);
    await act(async () => {
      window.dispatchEvent(new Event('focus'));
    });
    expect(attended).toBe(true);
  });

  it('stays attended when focus moves into a frame on the page', async () => {
    const focused = vi.mocked(document.hasFocus);
    await act(async () => {
      focused.mockReturnValue(false);
      window.dispatchEvent(new Event('blur'));
      focused.mockReturnValue(true);
      vi.advanceTimersByTime(0);
    });
    expect(attended).toBe(true);
  });
});
