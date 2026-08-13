import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ErrorBoundary from './ErrorBoundary';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Bomb({ armed }: { armed: boolean }) {
  if (armed) throw new Error('render exploded');
  return <div data-testid="child">safe child</div>;
}

describe('ErrorBoundary', () => {
  let container: HTMLDivElement;
  let root: Root;
  let consoleError: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    // React re-logs caught render errors; keep test output clean.
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    consoleError.mockRestore();
  });

  it('renders children when nothing throws', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <Bomb armed={false} />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[data-testid="child"]')).not.toBeNull();
  });

  it('contains a throwing child and shows the fallback', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <Bomb armed={true} />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[data-testid="child"]')).toBeNull();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(consoleError).toHaveBeenCalled();
  });

  it('recovers via the retry button once the cause is gone', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <Bomb armed={true} />
        </ErrorBoundary>,
      );
    });
    // The cause disappears (e.g. new data), but the boundary still holds.
    await act(async () => {
      root.render(
        <ErrorBoundary>
          <Bomb armed={false} />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[role="alert"]')).not.toBeNull();

    const button = container.querySelector('button');
    expect(button).not.toBeNull();
    await act(async () => {
      button!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(container.querySelector('[data-testid="child"]')).not.toBeNull();
  });

  it('uses a custom fallback render prop when provided', async () => {
    await act(async () => {
      root.render(
        <ErrorBoundary
          fallback={(retry) => (
            <button data-testid="custom" onClick={retry}>
              custom fallback
            </button>
          )}
        >
          <Bomb armed={true} />
        </ErrorBoundary>,
      );
    });
    expect(container.querySelector('[data-testid="custom"]')).not.toBeNull();
  });
});
