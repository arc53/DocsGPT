import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../components/ToolIcon', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));
vi.mock('../navigation/DetailBreadcrumb', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));

const getDevice = vi.fn();
vi.mock('../api/services/devicesService', () => ({
  default: {
    get: (...args: unknown[]) => getDevice(...args),
    listAudit: () => Promise.resolve({ entries: [] }),
  },
}));

import type { Device } from '../api/services/devicesService';
import type { UserToolType } from './types';
import RemoteDeviceConfig from './RemoteDeviceConfig';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const tool = {
  id: 'tool-1',
  name: 'remote_device',
  displayName: 'Remote device',
  config: { device_id: 'dev-1' },
} as unknown as UserToolType;

const device = (overrides: Partial<Device>): Device => ({
  id: 'dev-1',
  name: 'Laptop',
  approval_mode: 'ask',
  status: 'active',
  last_seen_at: null,
  ...overrides,
});

describe('RemoteDeviceConfig', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getDevice.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (d: Device) => {
    getDevice.mockResolvedValue(d);
    await act(async () => {
      root.render(<RemoteDeviceConfig tool={tool} handleGoBack={() => {}} />);
    });
  };

  const badges = () =>
    Array.from(container.querySelectorAll<HTMLElement>('[data-slot="badge"]'));

  it('shows an online device as a success badge', async () => {
    await render(device({ last_seen_at: new Date().toISOString() }));
    const pill = badges().find((el) =>
      el.textContent?.includes('settings.devices.online'),
    );
    expect(pill?.dataset.variant).toBe('success');
  });

  it('shows an offline device as a neutral badge', async () => {
    await render(device({}));
    const pill = badges().find((el) =>
      el.textContent?.includes('settings.devices.offline'),
    );
    expect(pill?.dataset.variant).toBe('neutral');
  });

  it('marks full approval with a destructive badge and alert', async () => {
    await render(device({ approval_mode: 'full' }));
    const pill = badges().find((el) =>
      el.textContent?.includes('settings.devices.approvalFull'),
    );
    expect(pill?.dataset.variant).toBe('destructive');

    const warning = Array.from(
      container.querySelectorAll<HTMLElement>('[role="alert"]'),
    ).find((el) =>
      el.textContent?.includes('settings.devices.fullAccessWarning'),
    );
    expect(warning?.className).toContain('text-destructive');
    expect(warning?.querySelector('svg')).not.toBeNull();
  });
});
