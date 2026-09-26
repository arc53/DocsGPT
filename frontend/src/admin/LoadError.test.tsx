import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { LoadError } from './AdminUI';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('LoadError', () => {
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

  it('renders a destructive empty state whose Retry re-runs the fetch', () => {
    const onRetry = vi.fn();
    act(() => {
      root.render(
        <LoadError message="Failed to load users." onRetry={onRetry} />,
      );
    });
    const block = container.querySelector('[data-slot="empty-state"]');
    expect(block?.getAttribute('data-tone')).toBe('destructive');
    expect(block?.getAttribute('role')).toBe('alert');
    expect(block?.textContent).toContain('Failed to load users.');

    const retry = container.querySelector('button');
    expect(retry?.textContent).toBe('Retry');
    act(() => retry?.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
