import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import TraceChips from './TraceChips';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TraceChips', () => {
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

  it('shows the summed cost of the trace', () => {
    act(() => root.render(<TraceChips counts={{ cost_usd: 0.0123 }} />));
    expect(container.textContent).toContain('$0.012');
  });

  it('hides the cost chip when nothing was priced', () => {
    act(() =>
      root.render(<TraceChips counts={{ llm_calls: 1, cost_usd: 0 }} />),
    );
    expect(container.textContent).not.toContain('$');
  });
});
