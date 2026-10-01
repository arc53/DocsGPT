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

  it('is an info Alert note (role="note") with the shared sentence and the variant icon', async () => {
    await act(async () => root.render(<ViewOnlyNotice />));
    const alert = container.querySelector('[data-slot="alert"]');
    expect(alert?.getAttribute('role')).toBe('note');
    expect(alert?.getAttribute('data-variant')).toBe('info');
    // One icon, the info variant's default.
    const icons = alert?.querySelectorAll(':scope > svg');
    expect(icons).toHaveLength(1);
    expect(icons?.[0].getAttribute('class')).toContain('lucide-info');
    expect(alert?.textContent).toBe('common.viewOnlyNotice');
  });
});
