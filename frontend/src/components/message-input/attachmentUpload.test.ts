import {
  checkAttachmentTask,
  createTaskQueue,
  parseStoredAttachment,
} from './attachmentUpload';

describe('parseStoredAttachment', () => {
  it('reads the single-file response', () => {
    expect(
      parseStoredAttachment({
        success: true,
        task_id: 'celery-1',
        attachment_id: 'srv-1',
      }),
    ).toEqual({ taskId: 'celery-1', attachmentId: 'srv-1' });
  });

  it('reads the first task of a tasks[] response', () => {
    expect(
      parseStoredAttachment({
        success: true,
        tasks: [{ task_id: 'celery-2', attachment_id: 'srv-2' }],
      }),
    ).toEqual({ taskId: 'celery-2', attachmentId: 'srv-2' });
  });

  it('keeps a response without an attachment id usable', () => {
    expect(parseStoredAttachment({ task_id: 'celery-3' })).toEqual({
      taskId: 'celery-3',
      attachmentId: undefined,
    });
  });

  it('returns null when no task was queued', () => {
    expect(parseStoredAttachment({ success: true, tasks: [] })).toBeNull();
    expect(parseStoredAttachment({ message: 'nope' })).toBeNull();
    expect(parseStoredAttachment(null)).toBeNull();
    expect(parseStoredAttachment('text')).toBeNull();
  });
});

describe('createTaskQueue', () => {
  const deferred = () => {
    let resolve!: () => void;
    let reject!: (err: Error) => void;
    const promise = new Promise<void>((res, rej) => {
      resolve = res;
      reject = rej;
    });
    return { promise, resolve, reject };
  };

  it('runs at most `concurrency` tasks at once, in order', async () => {
    const queue = createTaskQueue(2);
    const gates = [deferred(), deferred(), deferred(), deferred()];
    const started: number[] = [];
    gates.forEach((gate, i) =>
      queue.push(() => {
        started.push(i);
        return gate.promise;
      }),
    );
    expect(started).toEqual([0, 1]);

    gates[1].resolve();
    await vi.waitFor(() => expect(started).toEqual([0, 1, 2]));

    gates[0].resolve();
    await vi.waitFor(() => expect(started).toEqual([0, 1, 2, 3]));
  });

  it('keeps going after a task throws', async () => {
    const queue = createTaskQueue(1);
    const ran: string[] = [];
    queue.push(async () => {
      ran.push('bad');
      throw new Error('boom');
    });
    queue.push(async () => {
      ran.push('next');
    });
    await vi.waitFor(() => expect(ran).toEqual(['bad', 'next']));
  });
});

describe('checkAttachmentTask', () => {
  const answer = (status: number, body: unknown) =>
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

  it('reads a task no worker has taken yet as queued', async () => {
    const getTaskStatus = answer(200, { status: 'PENDING', result: null });
    await expect(
      checkAttachmentTask('celery-1', 'tok', getTaskStatus),
    ).resolves.toEqual({ state: 'queued' });
    expect(getTaskStatus).toHaveBeenCalledWith('celery-1', 'tok');
  });

  it.each(['STARTED', 'PROGRESS', 'RETRY', 'SUCCESS'])(
    'reads %s as taken by a worker',
    async (status) => {
      await expect(
        checkAttachmentTask('c', null, answer(200, { status })),
      ).resolves.toEqual({ state: 'started' });
    },
  );

  it('reads a failure with its reason', async () => {
    await expect(
      checkAttachmentTask(
        'c',
        null,
        answer(200, { status: 'FAILURE', result: 'Could not parse' }),
      ),
    ).resolves.toEqual({ state: 'failed', message: 'Could not parse' });
  });

  it('reads no reachable worker as unavailable', async () => {
    await expect(
      checkAttachmentTask('c', null, answer(503, { success: false })),
    ).resolves.toEqual({ state: 'unavailable' });
  });

  it('reads any other answer, or none, as unknown', async () => {
    await expect(
      checkAttachmentTask('c', null, answer(400, { success: false })),
    ).resolves.toEqual({ state: 'unknown' });
    await expect(
      checkAttachmentTask('c', null, vi.fn().mockRejectedValue(new Error())),
    ).resolves.toEqual({ state: 'unknown' });
  });
});
