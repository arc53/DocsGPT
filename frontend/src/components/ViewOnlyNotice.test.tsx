import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ViewOnlyNotice from './ViewOnlyNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ViewOnlyNotice', () => {
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

  it('is a quiet default Alert (role="note") with the shared sentence', async () => {
    await act(async () => root.render(<ViewOnlyNotice />));
    const alert = container.querySelector('[data-slot="alert"]');
    expect(alert?.getAttribute('role')).toBe('note');
    expect(alert?.getAttribute('data-variant')).toBe('default');
    expect(alert?.querySelector('svg')).not.toBeNull();
    expect(alert?.textContent).toBe('common.viewOnlyNotice');
  });
});
