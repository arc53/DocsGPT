import {
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../../workspace/requestWorkspace';
import workspacesService from './workspacesService';

type Call = { url: string; init: RequestInit };
const calls: Call[] = [];
let answer: () => Response;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      calls.push({ url, init });
      return Promise.resolve(answer());
    }),
  );
  setRequestWorkspace('t1', 1);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setRequestWorkspace('personal', 0);
});

const headers = (i = 0) => calls[i].init.headers as Record<string, string>;

const BODY = {
  to: { workspace: 't1' },
  items: [{ type: 'agent' as const, id: 'a1' }],
};

describe('workspacesService', () => {
  it('lists the workspaces', async () => {
    answer = () =>
      json({
        workspaces: [
          { id: 'personal', kind: 'personal', name: 'Personal' },
          { id: 't1', kind: 'team', name: 'Ops', role: 'admin' },
        ],
      });
    const rows = await workspacesService.list({ token: 'tok' });
    expect(calls[0].url).toMatch(/\/api\/workspaces$/);
    expect(headers().Authorization).toBe('Bearer tok');
    expect(rows.map((r) => r.id)).toEqual(['personal', 't1']);
  });

  it('rejects a failed list', async () => {
    answer = () => json({ success: false, message: 'Unauthorized' }, 401);
    await expect(workspacesService.list({ token: null })).rejects.toThrow();
  });

  it('plans a move and hands back the plan', async () => {
    answer = () => json({ success: true, plan: { fingerprint: 'fp' } });
    const result = await workspacesService.planMove(BODY, { token: 'tok' });
    expect(calls[0].url).toMatch(/\/api\/workspace_moves\/plan$/);
    expect(calls[0].init.method).toBe('POST');
    expect(JSON.parse(String(calls[0].init.body))).toEqual(BODY);
    expect(result).toEqual({
      ok: true,
      status: 200,
      plan: { fingerprint: 'fp' },
    });
  });

  it('plans with another workspace in the header when asked', async () => {
    answer = () => json({ success: true, plan: {} });
    await workspacesService.planMove(BODY, {
      token: 'tok',
      workspace: 'personal',
    });
    expect(headers()[WORKSPACE_HEADER]).toBe('personal');
    await workspacesService.planMove(BODY, { token: 'tok' });
    expect(headers(1)[WORKSPACE_HEADER]).toBe('t1');
  });

  it('applies a move with its fingerprint', async () => {
    answer = () => json({ success: true, moved: { fingerprint: 'fp' } });
    const result = await workspacesService.applyMove(
      { ...BODY, fingerprint: 'fp' },
      { token: 'tok' },
    );
    expect(calls[0].url).toMatch(/\/api\/workspace_moves$/);
    expect(JSON.parse(String(calls[0].init.body)).fingerprint).toBe('fp');
    expect(result).toEqual({
      ok: true,
      status: 200,
      plan: { fingerprint: 'fp' },
    });
  });

  it('hands back a refusal with its code and the rest of its body', async () => {
    answer = () =>
      json(
        {
          success: false,
          error: 'move_plan_changed',
          message: 'The plan changed',
          plan: { fingerprint: 'fp2' },
        },
        409,
      );
    const result = await workspacesService.applyMove(
      { ...BODY, fingerprint: 'fp' },
      { token: 'tok' },
    );
    expect(result).toEqual({
      ok: false,
      status: 409,
      error: 'move_plan_changed',
      message: 'The plan changed',
      body: {
        success: false,
        error: 'move_plan_changed',
        message: 'The plan changed',
        plan: { fingerprint: 'fp2' },
      },
    });
  });

  it('reads a non-JSON failure as move_failed', async () => {
    answer = () => new Response('Bad gateway', { status: 502 });
    const result = await workspacesService.planMove(BODY, { token: 'tok' });
    expect(result).toMatchObject({
      ok: false,
      status: 502,
      error: 'move_failed',
    });
  });
});
