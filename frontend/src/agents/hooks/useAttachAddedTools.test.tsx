import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import { useAttachAddedTools } from './useAttachAddedTools';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Tool = { id: string };

describe('useAttachAddedTools', () => {
  let container: HTMLDivElement;
  let root: Root;
  let attachCreated: ReturnType<typeof useAttachAddedTools<Tool>>;

  function Probe({ reload }: { reload: () => Promise<Tool[] | null> }) {
    attachCreated = useAttachAddedTools(reload);
    return null;
  }

  const render = (reload: () => Promise<Tool[] | null>) =>
    act(async () => root.render(<Probe reload={reload} />));

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });

  afterEach(() => act(async () => root.unmount()));

  it('reloads, then attaches the created tools the list holds', async () => {
    const reload = vi.fn(async () => [{ id: 'a' }, { id: 'B' }, { id: 'c' }]);
    await render(reload);
    const attach = vi.fn();
    await act(async () => attachCreated(['b', 'a', 'gone'], attach));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(attach).toHaveBeenCalledWith([{ id: 'a' }, { id: 'B' }]);
  });

  it('still reloads when nothing was created, and attaches nothing', async () => {
    const reload = vi.fn(async () => [{ id: 'a' }]);
    await render(reload);
    const attach = vi.fn();
    await act(async () => attachCreated([], attach));
    expect(reload).toHaveBeenCalledTimes(1);
    expect(attach).not.toHaveBeenCalled();
  });

  it('attaches nothing once the opener has gone, or when the reload fails', async () => {
    let finish: (tools: Tool[]) => void = () => undefined;
    await render(
      () =>
        new Promise<Tool[]>((resolve) => {
          finish = resolve;
        }),
    );
    const attach = vi.fn();
    const pending = attachCreated(['a'], attach);
    await act(async () => root.unmount());
    finish([{ id: 'a' }]);
    await pending;
    expect(attach).not.toHaveBeenCalled();

    root = createRoot(container);
    await render(() => Promise.reject(new Error('down')));
    await act(async () => attachCreated(['a'], attach));
    expect(attach).not.toHaveBeenCalled();
  });
});
