import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

const state = {
  preference: {
    token: 'token',
    agents: [] as unknown[],
    sharedAgents: [],
    selectedAgent: null,
  },
};
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) => selector(state),
}));
const getAgent = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({ default: { getAgent } }));

import AgentRouteGuard from '../AgentRouteGuard';
import { useAgent } from './useAgent';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const respond = (body: unknown, ok = true) =>
  Promise.resolve({ ok, json: () => Promise.resolve(body) });
const RECORD = { id: 'a1', name: 'Carrier FAQ', allowed_actions: ['view'] };

describe('useAgent', () => {
  let container: HTMLDivElement;
  let root: Root;
  let seen: ReturnType<typeof useAgent>;

  function Page() {
    seen = useAgent('a1');
    return <p data-testid="page">{seen.agent?.name}</p>;
  }

  beforeEach(() => {
    getAgent.mockReset();
    state.preference.agents = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (guarded: boolean) => {
    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/logs/a1']}>
          <Routes>
            <Route
              path="/agents/manage/logs/:agentId"
              element={
                guarded ? (
                  <AgentRouteGuard action="view">
                    <Page />
                  </AgentRouteGuard>
                ) : (
                  <Page />
                )
              }
            />
            <Route path="/agents/manage" element={<p>list</p>} />
          </Routes>
        </MemoryRouter>,
      ),
    );
    await act(async () => undefined);
  };

  it('reads the agent', async () => {
    getAgent.mockReturnValue(respond(RECORD));
    await render(false);
    expect(getAgent).toHaveBeenCalledWith('a1', 'token');
    expect(seen.agent).toEqual(RECORD);
    expect(seen.error).toBe(false);
  });

  // FX-12: the route guard has just read the record; the page takes it.
  it('takes the record the route guard read instead of reading it again', async () => {
    getAgent.mockReturnValue(respond(RECORD));
    await render(true);
    expect(getAgent).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="page"]')!.textContent).toBe(
      'Carrier FAQ',
    );
  });

  it('keeps the record the guard read when the agent list lands meanwhile', async () => {
    getAgent.mockReturnValue(respond(RECORD));
    await render(true);
    state.preference.agents = [RECORD];
    await render(true);
    expect(getAgent).toHaveBeenCalledTimes(1);
    expect(seen.agent).toEqual(RECORD);
  });

  it('reads it itself when the guard decided from the agent list', async () => {
    state.preference.agents = [RECORD];
    getAgent.mockReturnValue(respond({ ...RECORD, config: {} }));
    await render(true);
    expect(getAgent).toHaveBeenCalledTimes(1);
    expect(seen.agent).toEqual({ ...RECORD, config: {} });
  });

  // DESIGN › Load errors: a failure is an error the page shows, with Retry.
  it('says the read failed, and reads again on reload', async () => {
    getAgent.mockReturnValue(respond({}, false));
    await render(false);
    expect(seen.error).toBe(true);
    expect(seen.agent).toBeUndefined();
    getAgent.mockReturnValue(respond(RECORD));
    await act(async () => seen.reload());
    await act(async () => undefined);
    expect(getAgent).toHaveBeenCalledTimes(2);
    expect(seen.error).toBe(false);
    expect(seen.agent).toEqual(RECORD);
  });

  it('reads the record again on reload, keeping the one it has meanwhile', async () => {
    getAgent.mockReturnValue(respond(RECORD));
    await render(true);
    let resolve: (value: unknown) => void = () => undefined;
    getAgent.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    await act(async () => seen.reload());
    expect(seen.agent).toEqual(RECORD);
    await act(async () =>
      resolve({
        ok: true,
        json: () => Promise.resolve({ ...RECORD, name: 'Renamed' }),
      }),
    );
    expect(getAgent).toHaveBeenCalledTimes(2);
    expect(seen.agent?.name).toBe('Renamed');
  });
});
