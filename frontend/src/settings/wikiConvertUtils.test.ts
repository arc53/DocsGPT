import { describe, expect, it, vi } from 'vitest';

import {
  interpretTaskStatus,
  pollTaskOnce,
  startWikiConversion,
} from './wikiConvertUtils';

const jsonResponse = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

describe('startWikiConversion', () => {
  it('returns enabled for a blank source ({enabled:true}, no task)', async () => {
    const convertToWiki = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true, enabled: true }));

    const result = await startWikiConversion({ convertToWiki }, 'src-1', 'tok');

    expect(convertToWiki).toHaveBeenCalledWith('src-1', 'tok');
    expect(result).toEqual({ status: 'enabled' });
  });

  it('returns the task id for a fileful source', async () => {
    const convertToWiki = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true, task_id: 't-9' }));

    const result = await startWikiConversion({ convertToWiki }, 'src-1', 'tok');

    expect(result).toEqual({ status: 'task', taskId: 't-9' });
  });

  it('maps 403 to forbidden', async () => {
    const convertToWiki = vi.fn().mockResolvedValue(jsonResponse(403, {}));
    const result = await startWikiConversion({ convertToWiki }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'forbidden' });
  });

  it('maps 409 to conflict with the server message', async () => {
    const convertToWiki = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { message: 'still ingesting' }));
    const result = await startWikiConversion({ convertToWiki }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'conflict', message: 'still ingesting' });
  });

  it('maps a network throw to a generic error', async () => {
    const convertToWiki = vi.fn().mockRejectedValue(new Error('offline'));
    const result = await startWikiConversion({ convertToWiki }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'error' });
  });
});

describe('interpretTaskStatus', () => {
  it('parses a SUCCESS summary (pages + skipped list)', () => {
    const result = interpretTaskStatus('SUCCESS', {
      status: 'converted',
      pages_created: 12,
      skipped: [{ file: 'a.png', reason: 'unsupported' }],
    });
    expect(result).toEqual({
      status: 'done',
      summary: {
        pagesCreated: 12,
        skipped: [{ file: 'a.png', reason: 'unsupported' }],
      },
    });
  });

  it('defaults missing summary fields', () => {
    const result = interpretTaskStatus('SUCCESS', {});
    expect(result).toEqual({
      status: 'done',
      summary: { pagesCreated: 0, skipped: [] },
    });
  });

  it('maps FAILURE to failed', () => {
    expect(interpretTaskStatus('FAILURE', 'boom')).toEqual({
      status: 'failed',
      message: 'boom',
    });
  });

  it('treats other statuses as pending', () => {
    expect(interpretTaskStatus('PENDING', null)).toEqual({ status: 'pending' });
    expect(interpretTaskStatus('STARTED', null)).toEqual({ status: 'pending' });
  });
});

describe('pollTaskOnce', () => {
  it('returns the parsed summary on success', async () => {
    const getTaskStatus = vi.fn().mockResolvedValue(
      jsonResponse(200, {
        status: 'SUCCESS',
        result: { pages_created: 3, skipped: [] },
      }),
    );
    const result = await pollTaskOnce({ getTaskStatus }, 't-1', 'tok');
    expect(result).toEqual({
      status: 'done',
      summary: { pagesCreated: 3, skipped: [] },
    });
  });

  it('returns pending on a non-ok response', async () => {
    const getTaskStatus = vi.fn().mockResolvedValue(jsonResponse(503, {}));
    const result = await pollTaskOnce({ getTaskStatus }, 't-1', 'tok');
    expect(result).toEqual({ status: 'pending' });
  });
});
