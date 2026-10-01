import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const listAudit = vi.hoisted(() => vi.fn());
vi.mock('../api/services/devicesService', () => ({
  default: { listAudit: (...a: unknown[]) => listAudit(...a) },
}));

import DeviceAuditList from './DeviceAuditList';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const entry = (i: number) => ({
  id: `e${i}`,
  command: `ls ${i}`,
  decision: 'approved',
  exit_code: 0,
  duration_ms: 12,
  created_at: '2026-09-30T09:00:00Z',
});

describe('DeviceAuditList', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listAudit.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    await act(async () =>
      root.render(<DeviceAuditList deviceId="d1" token="t" />),
    );
    for (let i = 0; i < 4; i += 1) await act(async () => Promise.resolve());
  };

  it('asks for the newest 50 commands and caps them in an inner scroller', async () => {
    listAudit.mockResolvedValue({
      entries: Array.from({ length: 50 }, (_, i) => entry(i)),
    });
    await render();
    expect(listAudit).toHaveBeenCalledWith('d1', 't', 50, 0);
    const scroller = container.querySelector('ul')!.parentElement!;
    expect(scroller.className).toContain('max-h-[45svh]');
    expect(scroller.className).toContain('scrollbar-overlay');
    expect(container.querySelectorAll('li')).toHaveLength(50);
    // A full page: more may follow, so the status strip is there.
    expect(
      container.querySelector('[data-slot="load-more-status"]'),
    ).not.toBeNull();
  });

  it('says there is no activity yet', async () => {
    listAudit.mockResolvedValue({ entries: [] });
    await render();
    expect(container.textContent).toContain('settings.devices.auditEmpty');
  });

  it('a failed load offers Retry instead of "no activity"', async () => {
    listAudit.mockRejectedValueOnce(new Error('down'));
    listAudit.mockResolvedValue({ entries: [entry(1)] });
    await render();
    expect(container.textContent).not.toContain('settings.devices.auditEmpty');
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    expect(retry.className).toContain('rounded-full');
    await act(async () => retry.click());
    for (let i = 0; i < 4; i += 1) await act(async () => Promise.resolve());
    expect(container.querySelectorAll('li')).toHaveLength(1);
  });

  it('shows the em dash for a missing exit code, duration and time', async () => {
    listAudit.mockResolvedValue({
      entries: [
        { ...entry(1), exit_code: null, duration_ms: null, created_at: null },
      ],
    });
    await render();
    const text = container.querySelector('li')!.textContent!;
    expect(text).toContain('settings.devices.auditExit: —');
    expect(text).not.toContain('-');
  });
});
