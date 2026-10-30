import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { time?: string }) =>
      opts?.time ? `${key}(${opts.time})` : key,
  }),
}));

vi.mock('../components/ToolIcon', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));
vi.mock('../navigation/DetailBreadcrumb', () => ({ default: () => null }));
// The revoke confirm's props; the test calls its handleSubmit directly.
const confirmProps: { current: Record<string, unknown> | null } = {
  current: null,
};
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: Record<string, unknown>) => {
    confirmProps.current = props;
    return null;
  },
}));

const getDevice = vi.fn();
const revokeDevice = vi.fn();
vi.mock('../api/services/devicesService', () => ({
  default: {
    get: (...args: unknown[]) => getDevice(...args),
    revoke: (...args: unknown[]) => revokeDevice(...args),
    listAudit: () => Promise.resolve({ entries: [] }),
  },
}));

import type { Device } from '../api/services/devicesService';
import type { UserToolType } from './types';
import RemoteDeviceConfig from './RemoteDeviceConfig';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const goBack = vi.fn();

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
    revokeDevice.mockReset();
    goBack.mockReset();
    confirmProps.current = null;
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
      root.render(<RemoteDeviceConfig tool={tool} handleGoBack={goBack} />);
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

  it('says when an offline device was last seen with the shared relative time', async () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    await render(device({ last_seen_at: fiveMinutesAgo }));
    const pill = badges().find((el) =>
      el.textContent?.includes('settings.devices.offline'),
    )!;
    expect(pill.textContent).toContain('settings.devices.seen(5 minutes ago)');
  });

  it('shows the em dash for a device never seen', async () => {
    await render(device({}));
    const lastSeen = Array.from(container.querySelectorAll('dt')).find(
      (el) => el.textContent === 'settings.devices.lastSeenLabel',
    )!;
    expect(lastSeen.nextElementSibling?.textContent).toBe('—');
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

  // Revoke is the device's ⋯ at the end of the crumb row, after Save: no
  // danger-zone card.
  it("puts Revoke in the device's menu after Save", async () => {
    await render(device({}));
    expect(container.querySelector('[data-slot="card"][data-tone]')).toBeNull();
    const menu = container.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.tools.toolActions"]',
    )!;
    expect(menu.dataset.size).toBe('icon');
    const save = menu.previousElementSibling as HTMLElement;
    expect(save.textContent).toBe('settings.tools.save');
    expect(save.dataset.size).toBe('field');
    await act(async () => {
      menu.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
    const revoke = Array.from(
      document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => item.textContent === 'settings.devices.revoke')!;
    expect(revoke.dataset.variant).toBe('destructive');
    await act(async () => revoke.click());
    expect(confirmProps.current!.modalState).toBe('ACTIVE');
  });

  it('opens Recent activity with a link toggle under its header, no frame', async () => {
    await render(device({}));
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button'),
    ).find((el) => el.textContent === 'settings.devices.auditShow')!;
    expect(toggle).toBeDefined();
    expect(toggle.dataset.variant).toBe('link');
    expect(toggle.dataset.size).toBe('sm');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = container.querySelector<HTMLElement>(
      `#${CSS.escape(toggle.getAttribute('aria-controls')!)}`,
    )!;
    expect(body.dataset.slot).toBe('collapsible');
    expect(body.dataset.state).toBe('closed');
    const section = toggle.closest('section')!;
    expect(section.querySelector('.rounded-xl.border')).toBeNull();
    expect(section.querySelector('h3')?.textContent).toBe(
      'settings.devices.auditTitle',
    );
    await act(async () => toggle.click());
    expect(toggle.textContent).toBe('settings.devices.auditHide');
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
  });

  it('a failed revoke rejects so the confirm stays open on the device', async () => {
    revokeDevice.mockRejectedValue(new Error('Request failed (500)'));
    await render(device({}));
    const submit = confirmProps.current!.handleSubmit as () => unknown;
    let result: unknown;
    await act(async () => {
      result = submit();
      await (result as Promise<unknown>).catch(() => undefined);
    });
    await expect(result as Promise<unknown>).rejects.toThrow();
    expect(revokeDevice).toHaveBeenCalledWith('dev-1', 'token');
    expect(goBack).not.toHaveBeenCalled();
  });

  it('a successful revoke resolves and goes back to the list', async () => {
    revokeDevice.mockResolvedValue(undefined);
    await render(device({}));
    const submit = confirmProps.current!.handleSubmit as () => unknown;
    await act(async () => {
      await submit();
    });
    expect(goBack).toHaveBeenCalledTimes(1);
  });
});
