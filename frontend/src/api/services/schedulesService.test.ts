import { configureStore } from '@reduxjs/toolkit';
import { afterEach, describe, expect, it, vi } from 'vitest';

import schedulesReducer, {
  loadRunsForSchedule,
  loadSchedulesForAgent,
  selectSchedulesLoadError,
} from '../../agents/schedules/schedulesSlice';
import apiClient from '../client';
import schedulesService from './schedulesService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }) as unknown as Response;

describe('schedulesService.statsForAgent', () => {
  it('returns the stats body on success', async () => {
    const body = { days: 30, runs: 4, failed: 1, tokens: 120 };
    vi.spyOn(apiClient, 'get').mockResolvedValue(response(body));

    await expect(schedulesService.statsForAgent('a1', 't')).resolves.toEqual(
      body,
    );
  });

  it('rejects on an error response instead of returning its body as stats', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'Agent not found' }, 404),
    );

    await expect(schedulesService.statsForAgent('a1', 't')).rejects.toThrow();
  });
});

describe('schedulesService GET errors', () => {
  it('rejects an agent list error rather than returning it as schedules', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'access denied' }, 403),
    );

    await expect(schedulesService.listForAgent('a1', 't')).rejects.toThrow(
      'access denied',
    );
  });

  it('rejects a run history error rather than returning it as runs', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'access denied' }, 403),
    );

    await expect(schedulesService.listRuns('s1', 50, 0, 't')).rejects.toThrow(
      'access denied',
    );
  });

  it('rejects an individual schedule that cannot be found', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'schedule not found' }, 404),
    );

    await expect(schedulesService.get('s1', 't')).rejects.toThrow(
      'schedule not found',
    );
  });

  it('rejects a proxy error page without exposing its JSON parse error', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("Unexpected token '<'");
      },
    } as unknown as Response);

    await expect(schedulesService.listForAgent('a1', 't')).rejects.toThrow(
      /^$/,
    );
  });
});

describe('schedule loads after an HTTP error', () => {
  const makeStore = () =>
    configureStore({ reducer: { schedules: schedulesReducer } });

  it('keeps an agent list on a refused reload', async () => {
    vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce(response({ schedules: [{ id: 's1' }] }))
      .mockResolvedValueOnce(
        response({ success: false, message: 'access denied' }, 403),
      );
    const store = makeStore();
    const args = { agentId: 'a1', token: 't' };
    await store.dispatch(loadSchedulesForAgent(args));
    const schedules = store.getState().schedules.byAgent.a1;

    const action = await store.dispatch(loadSchedulesForAgent(args));

    expect(action.type).toBe(loadSchedulesForAgent.rejected.type);
    expect(store.getState().schedules.byAgent.a1).toEqual(schedules);
    expect(selectSchedulesLoadError(store.getState(), 'a1')).toBe(
      'access denied',
    );
  });

  it('records a fallback error when a gateway returns HTML', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new SyntaxError("Unexpected token '<'");
      },
    } as unknown as Response);
    const store = makeStore();

    const action = await store.dispatch(
      loadSchedulesForAgent({ agentId: 'a1', token: 't' }),
    );

    expect(action.type).toBe(loadSchedulesForAgent.rejected.type);
    expect(selectSchedulesLoadError(store.getState(), 'a1')).toBe(
      'failed to load schedules',
    );
    expect(store.getState().schedules.byAgent.a1).toBeUndefined();
  });

  it('keeps run history and does not throw on a refused reload', async () => {
    vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce(response({ runs: [{ id: 'r1' }] }))
      .mockResolvedValueOnce(
        response({ success: false, message: 'access denied' }, 403),
      );
    const store = makeStore();
    const args = { id: 's1', token: 't' };
    await store.dispatch(loadRunsForSchedule(args));
    const runs = store.getState().schedules.runsBySchedule.s1;

    await expect(
      store.dispatch(loadRunsForSchedule(args)),
    ).resolves.toMatchObject({ type: loadRunsForSchedule.rejected.type });
    expect(store.getState().schedules.runsBySchedule.s1).toEqual(runs);
  });
});

describe('schedulesService create and update errors', () => {
  it('rejects an update with the server message', async () => {
    vi.spyOn(apiClient, 'put').mockResolvedValue(
      response({ success: false, message: 'run_at is in the past.' }, 400),
    );

    await expect(
      schedulesService.update('s1', { run_at: '2020-01-01T00:00:00Z' }, 't'),
    ).rejects.toThrow('run_at is in the past.');
  });

  it('rejects a create with the server message', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response(
        { success: false, message: 'max schedules per user reached' },
        429,
      ),
    );

    await expect(
      schedulesService.create('a1', { instruction: 'x' }, 't'),
    ).rejects.toThrow('max schedules per user reached');
  });

  it('rejects a proxy error page without surfacing the JSON parse error', async () => {
    const json = vi.fn(async () => {
      throw new SyntaxError(
        'Unexpected token \'<\', "<html>" is not valid JSON',
      );
    });
    vi.spyOn(apiClient, 'put').mockResolvedValue({
      ok: false,
      status: 502,
      json,
    } as unknown as Response);

    const error = await schedulesService
      .update('s1', { instruction: 'x' }, 't')
      .then(
        () => null,
        (e: unknown) => e,
      );
    expect(error).toBeInstanceOf(Error);
    // No message: the form then shows only its own "couldn't save" text.
    expect((error as Error).message).toBe('');
  });

  it('rejects an error response whose JSON has no message with an empty message', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false }, 500),
    );

    await expect(
      schedulesService.create('a1', { instruction: 'x' }, 't'),
    ).rejects.toThrow(/^$/);
  });

  it('rejects a success status whose body is not JSON', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError("Unexpected token '<'");
      },
    } as unknown as Response);

    await expect(
      schedulesService.create('a1', { instruction: 'x' }, 't'),
    ).rejects.not.toThrow(/Unexpected token/);
  });

  it('returns the saved schedule on success', async () => {
    vi.spyOn(apiClient, 'put').mockResolvedValue(
      response({ success: true, schedule: { id: 's1' } }),
    );

    await expect(
      schedulesService.update('s1', { instruction: 'x' }, 't'),
    ).resolves.toEqual({ success: true, schedule: { id: 's1' } });
  });
});

describe('schedulesService run now and pause errors', () => {
  it('rejects a run now that the server refused', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false, message: 'a run is already in flight' }, 409),
    );

    await expect(schedulesService.runNow('s1', 't')).rejects.toThrow(
      'a run is already in flight',
    );
  });

  it('rejects a pause that the server refused', async () => {
    vi.spyOn(apiClient, 'patch').mockResolvedValue(
      response({ success: false, message: 'schedule is terminal' }, 409),
    );

    await expect(
      schedulesService.setPaused('s1', 'pause', 't'),
    ).rejects.toThrow('schedule is terminal');
  });

  it('returns the queued run on success', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: true, run: { id: 'r1' } }, 202),
    );

    await expect(schedulesService.runNow('s1', 't')).resolves.toEqual({
      success: true,
      run: { id: 'r1' },
    });
  });
});

describe('schedulesService.getRun', () => {
  it('rejects a run the server could not find', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ success: false, message: 'Run not found' }, 404),
    );

    await expect(schedulesService.getRun('s1', 'r1', 't')).rejects.toThrow(
      'Run not found',
    );
  });

  it('returns the run on success', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue(
      response({ run: { id: 'r1' } }),
    );

    await expect(schedulesService.getRun('s1', 'r1', 't')).resolves.toEqual({
      run: { id: 'r1' },
    });
  });
});
