import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import AgentStarters from './AgentStarters';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('AgentStarters', () => {
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

  const rows = () =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('[data-suggestion]'),
    );

  it('sends a starter, cleaned, as a question', async () => {
    const onAsk = vi.fn();
    await act(async () =>
      root.render(
        <AgentStarters
          starters={[' Run due diligence ', '', 'run due diligence', 'DPAs?']}
          onAsk={onAsk}
        />,
      ),
    );
    expect(rows().map((row) => row.textContent)).toEqual([
      'Run due diligence',
      'DPAs?',
    ]);
    await act(async () => rows()[1].click());
    expect(onAsk).toHaveBeenCalledWith('DPAs?');
  });

  it('draws nothing without starters', async () => {
    await act(async () =>
      root.render(<AgentStarters starters={undefined} onAsk={vi.fn()} />),
    );
    expect(container.innerHTML).toBe('');
  });
});
