import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import type { Attachment } from '../../upload/uploadSlice';
import { getSendReadiness, useArmedSend } from './armedSend';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const att = (over: Partial<Attachment> = {}): Attachment => ({
  id: 'a1',
  fileName: 'report.pdf',
  progress: 100,
  status: 'completed',
  taskId: 't1',
  ...over,
});

describe('getSendReadiness', () => {
  it('is ready with no attachments', () => {
    expect(getSendReadiness([])).toEqual({ state: 'ready' });
  });

  it('is ready when every attachment is completed', () => {
    expect(getSendReadiness([att(), att({ id: 'a2' })])).toEqual({
      state: 'ready',
    });
  });

  it('waits while any attachment is uploading or processing', () => {
    expect(
      getSendReadiness([
        att(),
        att({ id: 'a2', status: 'uploading', progress: 5 }),
        att({ id: 'a3', status: 'processing', progress: 40 }),
      ]),
    ).toEqual({ state: 'waiting', pendingCount: 2 });
  });

  it('blocks on a failed attachment, listing its name', () => {
    expect(
      getSendReadiness([
        att(),
        att({ id: 'a2', status: 'failed', fileName: 'broken.pdf' }),
      ]),
    ).toEqual({ state: 'blocked', failedNames: ['broken.pdf'] });
  });

  it('failed takes precedence over pending', () => {
    expect(
      getSendReadiness([
        att({ status: 'processing' }),
        att({ id: 'a2', status: 'failed', fileName: 'broken.pdf' }),
      ]),
    ).toEqual({ state: 'blocked', failedNames: ['broken.pdf'] });
  });
});

type HookApi = ReturnType<typeof useArmedSend>;

function Host({
  attachments,
  onFlush,
  api,
}: {
  attachments: Attachment[];
  onFlush: () => void;
  api: { current: HookApi | null };
}) {
  const hook = useArmedSend({ attachments, onFlush });
  api.current = hook;
  return null;
}

describe('useArmedSend', () => {
  let container: HTMLDivElement;
  let root: Root;
  let api: { current: HookApi | null };
  let onFlush: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    api = { current: null };
    onFlush = vi.fn<() => void>();
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (attachments: Attachment[]) => {
    await act(async () => {
      root.render(
        <Host attachments={attachments} onFlush={onFlush} api={api} />,
      );
    });
  };

  it('arms without flushing while attachments are pending', async () => {
    await render([att({ status: 'processing', progress: 30 })]);
    await act(async () => api.current!.arm());

    expect(api.current!.armed).toBe(true);
    expect(api.current!.readiness.state).toBe('waiting');
    expect(onFlush).not.toHaveBeenCalled();
  });

  it('auto-flushes exactly once when all attachments complete', async () => {
    await render([att({ status: 'processing', progress: 30 })]);
    await act(async () => api.current!.arm());

    await render([att()]);
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(api.current!.armed).toBe(false);

    // A later re-render with the same resolved attachments must not re-fire.
    await render([att()]);
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  it('holds the flush while a file is failed and resumes when it is removed', async () => {
    await render([att({ status: 'processing' })]);
    await act(async () => api.current!.arm());

    await render([att({ status: 'failed', fileName: 'broken.pdf' })]);
    expect(onFlush).not.toHaveBeenCalled();
    expect(api.current!.armed).toBe(true);
    expect(api.current!.readiness).toEqual({
      state: 'blocked',
      failedNames: ['broken.pdf'],
    });

    await render([]);
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(api.current!.armed).toBe(false);
  });

  it('cancel disarms and prevents the auto-flush', async () => {
    await render([att({ status: 'uploading', progress: 10 })]);
    await act(async () => api.current!.arm());
    await act(async () => api.current!.cancel());

    expect(api.current!.armed).toBe(false);

    await render([att()]);
    expect(onFlush).not.toHaveBeenCalled();
  });

  it('flush uses the latest onFlush callback', async () => {
    await render([att({ status: 'processing' })]);
    await act(async () => api.current!.arm());

    const lateFlush = vi.fn();
    await act(async () => {
      root.render(<Host attachments={[att()]} onFlush={lateFlush} api={api} />);
    });

    expect(onFlush).not.toHaveBeenCalled();
    expect(lateFlush).toHaveBeenCalledTimes(1);
  });
});
