import apiClient, { throttledApiClient } from './client';
import {
  onWorkspaceLost,
  onWorkspaceRoleRefused,
  setRequestWorkspace,
  WORKSPACE_HEADER,
} from '../workspace/requestWorkspace';

type Call = { url: string; init: RequestInit };

const calls: Call[] = [];
let answer: () => Response = () => new Response('{}', { status: 200 });

const headerOf = (call: Call): string | undefined =>
  (call.init.headers as Record<string, string>)[WORKSPACE_HEADER];

/** Lets the client's fire-and-forget body check run. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

beforeEach(() => {
  calls.length = 0;
  answer = () => new Response('{}', { status: 200 });
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

describe('apiClient: the workspace header', () => {
  const form = () => new FormData();
  const methods: [string, () => Promise<unknown>][] = [
    ['get', () => apiClient.get('/a', 'tok')],
    ['post', () => apiClient.post('/a', {}, 'tok')],
    ['postFormData', () => apiClient.postFormData('/a', form(), 'tok')],
    ['put', () => apiClient.put('/a', {}, 'tok')],
    ['patch', () => apiClient.patch('/a', {}, 'tok')],
    ['putFormData', () => apiClient.putFormData('/a', form(), 'tok')],
    ['delete', () => apiClient.delete('/a', 'tok')],
    ['throttled get', () => throttledApiClient.get('/b', 'tok')],
    ['throttled post', () => throttledApiClient.post('/b', {}, 'tok')],
  ];

  it.each(methods)('%s sends the current workspace', async (_name, send) => {
    await send();
    expect(calls).toHaveLength(1);
    expect(headerOf(calls[0])).toBe('t1');
  });

  it('sends personal explicitly in Personal', async () => {
    setRequestWorkspace('personal', 2);
    await apiClient.get('/a', null);
    expect(headerOf(calls[0])).toBe('personal');
  });

  it("lets a caller's header override it", async () => {
    await apiClient.get('/a', 'tok', { [WORKSPACE_HEADER]: 'personal' });
    expect(headerOf(calls[0])).toBe('personal');
    // The rest of the headers are still there.
    const headers = calls[0].init.headers as Record<string, string>;
    expect(headers.Authorization).toBe('Bearer tok');
  });

  it('reads the workspace at call time, not at import', async () => {
    await apiClient.get('/a', null);
    setRequestWorkspace('t2', 2);
    await apiClient.get('/a', null);
    expect(calls.map(headerOf)).toEqual(['t1', 't2']);
  });
});

describe('throttledApiClient: in-flight GETs are shared per workspace', () => {
  it('shares one request for the same URL in the same workspace', async () => {
    await Promise.all([
      throttledApiClient.get('/dedupe-same', 'tok'),
      throttledApiClient.get('/dedupe-same', 'tok'),
    ]);
    expect(calls).toHaveLength(1);
  });

  it('keeps a Personal and a team request for the same URL apart', async () => {
    const first = throttledApiClient.get('/dedupe-two', 'tok');
    setRequestWorkspace('personal', 2);
    const second = throttledApiClient.get('/dedupe-two', 'tok');
    await Promise.all([first, second]);
    expect(calls.map(headerOf).sort()).toEqual(['personal', 't1']);
  });
});

describe('apiClient: a lost or refused workspace', () => {
  it('reports a 404 workspace_not_found with the workspace it was sent for', async () => {
    const lost = vi.fn();
    const off = onWorkspaceLost(lost);
    answer = () =>
      new Response(
        JSON.stringify({ success: false, error: 'workspace_not_found' }),
        { status: 404 },
      );
    const response = await apiClient.get('/a', 'tok');
    await flush();
    expect(lost).toHaveBeenCalledWith('t1');
    // The caller still reads the body itself.
    expect((await response.json()).error).toBe('workspace_not_found');
    off();
  });

  it('leaves other 404s alone', async () => {
    const lost = vi.fn();
    const off = onWorkspaceLost(lost);
    answer = () =>
      new Response(JSON.stringify({ error: 'not_found' }), { status: 404 });
    await apiClient.get('/a', 'tok');
    answer = () => new Response('<html>nope</html>', { status: 404 });
    await apiClient.get('/a', 'tok');
    answer = () =>
      new Response(JSON.stringify({ error: 'workspace_not_found' }), {
        status: 200,
      });
    await apiClient.get('/a', 'tok');
    await flush();
    expect(lost).not.toHaveBeenCalled();
    off();
  });

  it('reports a 403 workspace_role_required', async () => {
    const refused = vi.fn();
    const off = onWorkspaceRoleRefused(refused);
    answer = () =>
      new Response(JSON.stringify({ error: 'workspace_role_required' }), {
        status: 403,
      });
    await apiClient.post('/a', {}, 'tok');
    await flush();
    expect(refused).toHaveBeenCalledWith('t1');
    off();
  });

  it('stops reporting once the handler is removed', async () => {
    const lost = vi.fn();
    onWorkspaceLost(lost)();
    answer = () =>
      new Response(JSON.stringify({ error: 'workspace_not_found' }), {
        status: 404,
      });
    await apiClient.get('/a', 'tok');
    await flush();
    expect(lost).not.toHaveBeenCalled();
  });
});
