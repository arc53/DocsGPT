import { describe, expect, it, vi } from 'vitest';

import {
  interpretTaskStatus,
  pollTaskOnce,
  startGraphRAG,
} from './graphragEnableUtils';

const jsonResponse = (status: number, body: unknown): Response =>
  ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  }) as unknown as Response;

describe('startGraphRAG', () => {
  it('returns the task id when extraction is enqueued', async () => {
    const enableGraphRAG = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true, task_id: 't-9' }));

    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');

    expect(enableGraphRAG).toHaveBeenCalledWith('src-1', 'tok');
    expect(result).toEqual({ status: 'task', taskId: 't-9' });
  });

  it('returns enabled when success has no task id', async () => {
    const enableGraphRAG = vi
      .fn()
      .mockResolvedValue(jsonResponse(200, { success: true }));

    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');

    expect(result).toEqual({ status: 'enabled' });
  });

  it('maps 403 to forbidden', async () => {
    const enableGraphRAG = vi.fn().mockResolvedValue(jsonResponse(403, {}));
    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'forbidden' });
  });

  it('maps 409 to conflict with the server message', async () => {
    const enableGraphRAG = vi
      .fn()
      .mockResolvedValue(jsonResponse(409, { message: 'still ingesting' }));
    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'conflict', message: 'still ingesting' });
  });

  it('maps a 400 unavailable to an error with the message', async () => {
    const enableGraphRAG = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(400, { success: false, message: 'pgvector required' }),
      );
    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'error', message: 'pgvector required' });
  });

  it('maps a network throw to a generic error', async () => {
    const enableGraphRAG = vi.fn().mockRejectedValue(new Error('offline'));
    const result = await startGraphRAG({ enableGraphRAG }, 'src-1', 'tok');
    expect(result).toEqual({ status: 'error' });
  });
});

describe('interpretTaskStatus', () => {
  it('parses a SUCCESS summary (nodes + edges + chunks)', () => {
    const result = interpretTaskStatus('SUCCESS', {
      nodes: 12,
      edges: 7,
      chunks_processed: 30,
      skipped_over_cap: 2,
      failed_chunks: 1,
    });
    expect(result).toEqual({
      status: 'done',
      summary: {
        nodes: 12,
        edges: 7,
        chunksProcessed: 30,
        skippedOverCap: 2,
        failedChunks: 1,
      },
    });
  });

  it('defaults missing summary fields', () => {
    const result = interpretTaskStatus('SUCCESS', {});
    expect(result).toEqual({
      status: 'done',
      summary: {
        nodes: 0,
        edges: 0,
        chunksProcessed: 0,
        skippedOverCap: 0,
        failedChunks: 0,
      },
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
        result: { nodes: 3, edges: 1, chunks_processed: 5 },
      }),
    );
    const result = await pollTaskOnce({ getTaskStatus }, 't-1', 'tok');
    expect(result).toEqual({
      status: 'done',
      summary: {
        nodes: 3,
        edges: 1,
        chunksProcessed: 5,
        skippedOverCap: 0,
        failedChunks: 0,
      },
    });
  });

  it('returns pending on a non-ok response', async () => {
    const getTaskStatus = vi.fn().mockResolvedValue(jsonResponse(503, {}));
    const result = await pollTaskOnce({ getTaskStatus }, 't-1', 'tok');
    expect(result).toEqual({ status: 'pending' });
  });
});
