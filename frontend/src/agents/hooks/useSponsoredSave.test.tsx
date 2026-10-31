import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { names?: string }) =>
      opts?.names ? `${key}:${opts.names}` : key,
    i18n: { language: 'en' },
  }),
}));
// The confirmation dialog as buttons that agree or decline.
vi.mock('../components/SponsorConfirmModal', () => ({
  default: ({
    confirmation,
    onConfirm,
    onCancel,
  }: {
    confirmation: { resources: { key: string }[] } | null;
    onConfirm: (keys: string[]) => void;
    onCancel: () => void;
  }) =>
    confirmation ? (
      <>
        <button
          type="button"
          data-testid="agree"
          onClick={() => onConfirm(confirmation.resources.map((r) => r.key))}
        />
        <button type="button" data-testid="decline" onClick={onCancel} />
      </>
    ) : null,
}));

import { type SponsoredSave, useSponsoredSave } from './useSponsoredSave';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
const AUDIENCE = {
  teams: [],
  api_key: false,
  public_link: false,
  webhook: false,
};
const RESOURCE = {
  key: 'tool:t1',
  type: 'tool' as const,
  id: 't1',
  name: 'Jira',
};

describe('useSponsoredSave', () => {
  let container: HTMLDivElement;
  let root: Root;
  let hook: SponsoredSave;
  const refresh = vi.fn();

  function Probe() {
    hook = useSponsoredSave({ refresh });
    return <>{hook.modal}</>;
  }

  beforeEach(async () => {
    refresh.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Probe />));
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const click = (id: string) =>
    act(async () =>
      container
        .querySelector<HTMLButtonElement>(`[data-testid="${id}"]`)!
        .click(),
    );

  it('sends the takeovers, then clears them and refreshes once saved', async () => {
    await act(async () => {
      void hook.takeOver(RESOURCE, 'Jira', AUDIENCE);
    });
    await click('agree');
    expect(hook.takeovers).toEqual(['tool:t1']);
    const send = vi.fn(async () => json(200, { success: true }));
    let result: Awaited<ReturnType<SponsoredSave['save']>> | undefined;
    await act(async () => {
      result = await hook.save(send, 'failed');
    });
    expect(send).toHaveBeenCalledWith(['tool:t1']);
    expect(result?.status).toBe('saved');
    expect(hook.takeovers).toEqual([]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('asks on a confirmation request and resends with the answer', async () => {
    const send = vi
      .fn()
      .mockResolvedValueOnce(
        json(409, {
          code: 'sponsor_confirmation_required',
          resources: [RESOURCE],
          audience: AUDIENCE,
        }),
      )
      .mockResolvedValueOnce(json(200, { success: true }));
    let pending: Promise<unknown> = Promise.resolve();
    await act(async () => {
      pending = hook.save(send, 'failed');
    });
    await click('agree');
    await act(async () => {
      expect(await pending).toMatchObject({ status: 'saved' });
    });
    expect(send).toHaveBeenLastCalledWith(['tool:t1']);
  });

  it('ends as cancelled when the caller declines', async () => {
    const send = vi.fn(async () =>
      json(409, {
        code: 'sponsor_confirmation_required',
        resources: [RESOURCE],
        audience: AUDIENCE,
      }),
    );
    let pending: Promise<unknown> = Promise.resolve();
    await act(async () => {
      pending = hook.save(send, 'failed');
    });
    await click('decline');
    await act(async () => {
      expect(await pending).toEqual({ status: 'cancelled' });
    });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('names what the caller may not sponsor', async () => {
    let result: unknown;
    await act(async () => {
      result = await hook.save(
        async () =>
          json(403, { code: 'sponsor_not_allowed', resources: [RESOURCE] }),
        'failed',
      );
    });
    expect(result).toMatchObject({
      status: 'failed',
      message: 'agents.form.sponsors.notAllowed:Jira',
    });
  });

  it('drops the takeovers and refreshes on an outdated confirmation', async () => {
    await act(async () => {
      void hook.takeOver(RESOURCE, 'Jira', AUDIENCE);
    });
    await click('agree');
    let result: unknown;
    await act(async () => {
      result = await hook.save(
        async () => json(400, { code: 'sponsor_confirmation_unexpected' }),
        'failed',
      );
    });
    expect(result).toMatchObject({
      status: 'failed',
      message: 'agents.form.sponsors.confirmationOutdated',
    });
    expect(hook.takeovers).toEqual([]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("gives the server's message, else the fallback", async () => {
    let result: unknown;
    await act(async () => {
      result = await hook.save(
        async () => json(400, { message: 'Name is taken' }),
        'failed',
      );
    });
    expect(result).toMatchObject({
      status: 'failed',
      message: 'Name is taken',
    });
    await act(async () => {
      result = await hook.save(
        async () => new Response('<html>', { status: 502 }),
        'failed',
      );
    });
    expect(result).toMatchObject({ status: 'failed', message: 'failed' });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('takes back a takeover', async () => {
    await act(async () => {
      void hook.takeOver(RESOURCE, 'Jira', AUDIENCE);
    });
    await click('agree');
    await act(async () => hook.undoTakeover('tool:t1'));
    expect(hook.takeovers).toEqual([]);
  });
});
