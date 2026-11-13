import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { WandButton } from './WandButton';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('WandButton', () => {
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

  it('keeps its button node when the label comes and goes', async () => {
    // A docked panel gives focus back to its opener only while that node
    // is still in the page: Resume (with a label) turning into Build must
    // not swap the button for a new one.
    await act(async () =>
      root.render(
        <WandButton mode="resume" label="Resume: step 2" onClick={() => {}} />,
      ),
    );
    const before = container.querySelector('button')!;
    await act(async () =>
      root.render(<WandButton mode="draft" onClick={() => {}} />),
    );
    expect(before.isConnected).toBe(true);
    expect(container.querySelector('button')).toBe(before);
    await act(async () =>
      root.render(
        <WandButton mode="resume" label="Resume: step 3" onClick={() => {}} />,
      ),
    );
    expect(container.querySelector('button')).toBe(before);
    expect(before.getAttribute('aria-label')).toBe('Resume: step 3');
  });
});
