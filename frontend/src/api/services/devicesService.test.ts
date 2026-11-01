import { afterEach, describe, expect, it, vi } from 'vitest';

import apiClient from '../client';
import devicesService, { DevicesApiError } from './devicesService';

afterEach(() => vi.restoreAllMocks());

const response = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const rejection = (request: Promise<unknown>) =>
  request.then(
    (value) => {
      throw new Error(`resolved with ${JSON.stringify(value)}`);
    },
    (reason: unknown) => reason as DevicesApiError,
  );

describe('devicesService HTTP errors', () => {
  it('rejects a revoke the server refused instead of resolving its error body', async () => {
    vi.spyOn(apiClient, 'delete').mockResolvedValue(
      response({ success: false, error: 'auth' }, 401),
    );

    const err = await rejection(devicesService.revoke('dev-1', 't'));
    expect(err).toBeInstanceOf(DevicesApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe('auth');
  });

  it('rejects an update instead of returning the error body as the device', async () => {
    vi.spyOn(apiClient, 'patch').mockResolvedValue(
      response({ success: false, error: 'auth' }, 401),
    );

    const err = await rejection(
      devicesService.update('dev-1', { name: 'Renamed' }, 't'),
    );
    expect(err).toBeInstanceOf(DevicesApiError);
    expect(err.status).toBe(401);
  });

  it('rejects a pairing the server could not create', async () => {
    vi.spyOn(apiClient, 'post').mockResolvedValue(
      response({ success: false, error: 'redis_unavailable' }, 503),
    );

    const err = await rejection(devicesService.startPairing('t', {}));
    expect(err).toBeInstanceOf(DevicesApiError);
    expect(err.status).toBe(503);
    expect(err.code).toBe('redis_unavailable');
  });

  it('rejects a device or pairing the server cannot find', async () => {
    vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce(
        response({ success: false, error: 'not_found' }, 404),
      )
      .mockResolvedValueOnce(
        response({ success: false, error: 'pairing_not_found' }, 404),
      );

    const device = await rejection(devicesService.get('dev-1', 't'));
    expect(device.status).toBe(404);
    expect(device.code).toBe('not_found');
    const pairing = await rejection(devicesService.pollPairing('dc_1', 't'));
    expect(pairing.status).toBe(404);
    expect(pairing.code).toBe('pairing_not_found');
  });

  it('rejects a proxy error page without exposing its JSON parse error', async () => {
    vi.spyOn(apiClient, 'delete').mockResolvedValue(
      new Response('<html>Bad gateway</html>', { status: 502 }),
    );

    const err = await rejection(devicesService.revoke('dev-1', 't'));
    expect(err).toBeInstanceOf(DevicesApiError);
    expect(err.status).toBe(502);
    expect(err.code).toBeUndefined();
    expect(err.message).not.toMatch(/JSON|token/i);
  });

  it('returns the body of a successful response', async () => {
    const saved = {
      id: 'dev-1',
      name: 'Renamed',
      approval_mode: 'ask',
      status: 'active',
    };
    vi.spyOn(apiClient, 'patch').mockResolvedValue(response(saved));
    vi.spyOn(apiClient, 'delete').mockResolvedValue(
      response({ success: true }),
    );

    await expect(
      devicesService.update('dev-1', { name: 'Renamed' }, 't'),
    ).resolves.toEqual(saved);
    await expect(devicesService.revoke('dev-1', 't')).resolves.toEqual({
      success: true,
    });
  });
});
