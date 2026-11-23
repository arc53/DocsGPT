import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const list = vi.hoisted(() => vi.fn());
vi.mock('../api/services/devicesService', () => ({ default: { list } }));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ preference: { token: 'tok' } }),
}));

import { useDeviceOnline } from './useDeviceOnline';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const DEVICE = { name: 'remote_device' };
const OTHER = { name: 'brave' };

describe('useDeviceOnline', () => {
  let container: HTMLDivElement;
  let root: Root;
  let seen: Map<string, boolean> | undefined;

  function Probe({
    open,
    tools,
  }: {
    open: boolean;
    tools: { name: string }[];
  }) {
    seen = useDeviceOnline(open, tools);
    return null;
  }

  beforeEach(() => {
    list.mockReset();
    seen = undefined;
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => act(() => root.unmount()));

  const render = (open: boolean, tools: { name: string }[]) =>
    act(async () => root.render(<Probe open={open} tools={tools} />));

  it('asks when a picker with a device opens, and maps each device', async () => {
    list.mockResolvedValue({
      devices: [
        { id: 'on', last_seen_at: new Date().toISOString() },
        { id: 'off', last_seen_at: '2020-01-01T00:00:00Z' },
      ],
    });
    await render(false, [DEVICE]);
    expect(list).not.toHaveBeenCalled();
    await render(true, [DEVICE]);
    expect(list).toHaveBeenCalledWith('tok');
    expect(seen?.get('on')).toBe(true);
    expect(seen?.get('off')).toBe(false);
  });

  it('never asks for a list without a device', async () => {
    await render(true, [OTHER]);
    expect(list).not.toHaveBeenCalled();
    expect(seen).toBeUndefined();
  });

  it('shows no status when the list fails', async () => {
    list.mockRejectedValue(new Error('401'));
    await render(true, [DEVICE]);
    expect(seen).toBeUndefined();
  });
});
