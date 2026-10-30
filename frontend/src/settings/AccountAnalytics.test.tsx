import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock('./Analytics', () => ({
  default: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="charts" />;
  },
}));
vi.mock('./components/UsageQuota', () => ({
  default: () => <div data-testid="quota" />,
}));

import AccountAnalytics from './AccountAnalytics';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Settings Analytics', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    seen.props = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  // IN-16: the window select in PageToolbar's action slot, beside the
  // intro, above the quota; the charts read the window from the page.
  it('puts the intro and the window in the page toolbar, above the quota', async () => {
    await act(async () => root.render(<AccountAnalytics />));
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('settings.analytics.subtitle');
    expect(
      toolbar.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    const quota = container.querySelector('[data-testid="quota"]')!;
    expect(
      toolbar.compareDocumentPosition(quota) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(seen.props.at(-1)).toEqual({ filterOption: 'last_30_days' });
  });
});
