import { afterEach, describe, expect, it, vi } from 'vitest';

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
