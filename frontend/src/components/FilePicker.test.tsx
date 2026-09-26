import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const validateConnectorSession = vi.fn();
const getConnectorFiles = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    validateConnectorSession: (...args: unknown[]) =>
      validateConnectorSession(...args),
    getConnectorFiles: (...args: unknown[]) => getConnectorFiles(...args),
    disconnectConnector: vi.fn(),
  },
}));

vi.mock('../utils/providerUtils', () => ({
  getSessionToken: () => 'session-token',
  setSessionToken: vi.fn(),
  removeSessionToken: vi.fn(),
}));

vi.mock('../components/ConnectorAuth', () => ({ default: () => null }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { FilePicker } from './FilePicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('FilePicker', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    validateConnectorSession.mockReset();
    getConnectorFiles.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('shows an expired session as a destructive alert', async () => {
    validateConnectorSession.mockResolvedValue({ ok: false });
    await act(async () => {
      root.render(
        <FilePicker
          provider="google_drive"
          token={null}
          onSelectionChange={() => undefined}
        />,
      );
    });
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('filePicker.sessionExpiredFor');
    expect(alert?.querySelector('svg')).not.toBeNull();
  });

  async function renderSharePoint() {
    validateConnectorSession.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        user_email: 'lena@meridian.example',
        allows_shared_content: true,
      }),
    });
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: true, files: [], next_page_token: null }),
    });
    await act(async () => {
      root.render(
        <FilePicker
          provider="share_point"
          token={null}
          onSelectionChange={() => undefined}
        />,
      );
    });
  }

  it('renders the drive switch as underline tabs with the active one marked', async () => {
    await renderSharePoint();
    const list = container.querySelector('[data-slot="tabs-list"]')!;
    expect(list.getAttribute('role')).toBe('tablist');
    expect(list.getAttribute('data-variant')).toBe('underline');
    const tabs = Array.from(
      list.querySelectorAll('[data-slot="tabs-trigger"][role="tab"]'),
    );
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'filePicker.myFiles',
      'filePicker.sharedWithMe',
    ]);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('aria-selected')).toBe('false');
    // The file list below is the active tab's panel.
    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.id).toBe(tabs[0].getAttribute('aria-controls'));
  });

  it('shows the folder trail as a breadcrumb with the current folder as the page', async () => {
    await renderSharePoint();
    const trail = container.querySelector('nav[aria-label="breadcrumb"]');
    expect(trail).not.toBeNull();
    const page = trail?.querySelector('[data-slot="breadcrumb-page"]');
    expect(page?.textContent).toBe('filePicker.myFiles');
    expect(page?.getAttribute('title')).toBe('filePicker.myFiles');
    expect(trail?.querySelector('button[disabled]')).toBeNull();
  });
});
