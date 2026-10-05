import userService from '../../api/services/userService';
import { parseUploadErrorMessage } from '../../constants/fileUpload';
import { guardUploadStall } from './uploadStallGuard';

/**
 * Attachment uploads in flight at once. Each file goes in its own request,
 * so one large or slow file neither holds the others back nor pushes a
 * batch over the server's request cap.
 */
export const ATTACHMENT_UPLOAD_CONCURRENCY = 4;

/**
 * Largest file the composer will upload. Mirrors the server's default
 * ``UPLOAD_MAX_FILE_BYTES``; the server stays the authority and reports its
 * own limit per file when a deployment sets a lower one.
 */
export const ATTACHMENT_MAX_BYTES = 100 * 1024 * 1024;

/**
 * How long a file the worker is parsing may go without a progress event
 * before the composer gives up on it.
 */
export const ATTACHMENT_IDLE_MS = 5 * 60_000;

/**
 * How long a stored file may wait for its first worker event before the
 * composer asks the task status where it stands.
 */
export const ATTACHMENT_QUEUE_CHECK_MS = 10 * 60_000;

/**
 * Status checks a still-queued file gets before the composer gives up on it:
 * an hour of waiting for a worker at ``ATTACHMENT_QUEUE_CHECK_MS``.
 */
export const ATTACHMENT_QUEUE_MAX_CHECKS = 6;

/** What the server returns for a file it stored and queued for parsing. */
export interface StoredAttachment {
  /** Celery task id. */
  taskId: string;
  /** Server attachment id; ``attachment.*`` events carry it as ``scope.id``. */
  attachmentId?: string;
}

/** How one file's upload ended. */
export type AttachmentUploadOutcome =
  | ({ kind: 'stored' } & StoredAttachment)
  /** The server answered but did not queue the file; ``message`` says why. */
  | { kind: 'rejected'; message?: string }
  /** No answer at all: a dropped connection, an unreadable file, a stall. */
  | { kind: 'network' };

type TaskEntry = { task_id?: unknown; attachment_id?: unknown };

/**
 * Read the stored attachment out of a ``/api/store_attachment`` response.
 *
 * A single file normally comes back as ``{task_id, attachment_id}``; the
 * ``tasks[]`` shape of a multi-file request is accepted too.
 *
 * Args:
 *   body: The parsed JSON response.
 *
 * Returns:
 *   The task and attachment ids, or null when no task was queued.
 */
export function parseStoredAttachment(body: unknown): StoredAttachment | null {
  if (!body || typeof body !== 'object') return null;
  const response = body as TaskEntry & { tasks?: unknown };
  const entry: TaskEntry | undefined =
    typeof response.task_id === 'string'
      ? response
      : Array.isArray(response.tasks)
        ? (response.tasks[0] as TaskEntry | undefined)
        : undefined;
  if (!entry || typeof entry.task_id !== 'string' || !entry.task_id) {
    return null;
  }
  return {
    taskId: entry.task_id,
    attachmentId:
      typeof entry.attachment_id === 'string' && entry.attachment_id
        ? entry.attachment_id
        : undefined,
  };
}

/**
 * Upload one file to ``/api/store_attachment``.
 *
 * Args:
 *   file: The file to send.
 *   options.url: The endpoint URL.
 *   options.token: Bearer token, when the user is signed in.
 *   options.onProgress: Called with the percent of the body sent.
 *   options.signal: Aborts the request (the chip was removed); the upload
 *     then ends as ``network``.
 *
 * Returns:
 *   How the upload ended. Never rejects.
 */
export function uploadAttachmentFile(
  file: File,
  options: {
    url: string;
    token?: string | null;
    onProgress?: (percent: number) => void;
    signal?: AbortSignal;
  },
): Promise<AttachmentUploadOutcome> {
  return new Promise((resolve) => {
    if (options.signal?.aborted) {
      resolve({ kind: 'network' });
      return;
    }
    const formData = new FormData();
    formData.append('file', file);
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) {
        options.onProgress?.(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }
      if (xhr.status === 200) {
        const stored = parseStoredAttachment(body);
        if (stored) {
          resolve({ kind: 'stored', ...stored });
          return;
        }
        // A 200 that queued nothing: its ``message`` is the success
        // copy, so it cannot serve as the reason.
        console.error('Unexpected upload response', xhr.responseText);
        resolve({ kind: 'rejected' });
        return;
      }
      console.error('Upload failed', xhr.status, xhr.responseText);
      resolve({
        kind: 'rejected',
        message: parseUploadErrorMessage(xhr.responseText),
      });
    };

    xhr.onerror =
      xhr.onabort =
      xhr.ontimeout =
        () => resolve({ kind: 'network' });

    xhr.open('POST', options.url);
    if (options.token) {
      xhr.setRequestHeader('Authorization', `Bearer ${options.token}`);
    }
    guardUploadStall(xhr);
    options.signal?.addEventListener('abort', () => xhr.abort(), {
      once: true,
    });
    xhr.send(formData);
  });
}

/**
 * Where a stored file's parse task stands, from the task-status endpoint.
 *
 * ``queued``: no worker has taken it yet. ``started``: a worker has (or has
 * finished; the outcome follows as an ``attachment.*`` event). ``failed``:
 * the task failed, with the reason when the endpoint gives one.
 * ``unavailable``: no worker answers at all. ``unknown``: no usable answer.
 */
export type AttachmentTaskState =
  | { state: 'queued' }
  | { state: 'started' }
  | { state: 'failed'; message?: string }
  | { state: 'unavailable' }
  | { state: 'unknown' };

const QUEUED_TASK_STATES = new Set(['PENDING', 'RECEIVED']);
const STARTED_TASK_STATES = new Set([
  'STARTED',
  'PROGRESS',
  'RETRY',
  'SUCCESS',
]);
const FAILED_TASK_STATES = new Set(['FAILURE', 'REVOKED']);

/**
 * Ask the task-status endpoint where a file's parse task stands.
 *
 * Args:
 *   taskId: The Celery task id the upload response returned.
 *   token: Bearer token, when the user is signed in.
 *   getTaskStatus: The status request; the user service's by default.
 *
 * Returns:
 *   The task's state. Never rejects.
 */
export async function checkAttachmentTask(
  taskId: string,
  token: string | null,
  getTaskStatus: (
    taskId: string,
    token: string | null,
  ) => Promise<Response> = userService.getTaskStatus,
): Promise<AttachmentTaskState> {
  let response: Response;
  try {
    response = await getTaskStatus(taskId, token);
  } catch {
    return { state: 'unknown' };
  }
  // The endpoint answers 503 when no worker replies to a ping.
  if (response.status === 503) return { state: 'unavailable' };
  if (!response.ok) return { state: 'unknown' };
  const body = (await response.json().catch(() => null)) as {
    status?: unknown;
    result?: unknown;
  } | null;
  const status = typeof body?.status === 'string' ? body.status : '';
  if (QUEUED_TASK_STATES.has(status)) return { state: 'queued' };
  if (STARTED_TASK_STATES.has(status)) return { state: 'started' };
  if (FAILED_TASK_STATES.has(status)) {
    const message =
      typeof body?.result === 'string' && body.result.trim()
        ? body.result
        : undefined;
    return message ? { state: 'failed', message } : { state: 'failed' };
  }
  return { state: 'unknown' };
}

/**
 * A first-in, first-out queue that runs at most ``concurrency`` tasks at
 * once. A task that throws does not stop the ones after it.
 *
 * Args:
 *   concurrency: The most tasks allowed to run at the same time.
 *
 * Returns:
 *   The queue; ``push`` adds a task and starts it when a slot is free, and
 *   returns a function that drops the task if it has not started yet.
 */
export function createTaskQueue(concurrency: number): {
  push: (task: () => Promise<void>) => () => void;
} {
  const pending: Array<() => Promise<void>> = [];
  let running = 0;

  const next = () => {
    while (running < concurrency && pending.length > 0) {
      const task = pending.shift()!;
      running += 1;
      let started: Promise<void>;
      try {
        started = task();
      } catch (err) {
        started = Promise.reject(err);
      }
      started
        .catch((err) => console.error('Queued task failed', err))
        .finally(() => {
          running -= 1;
          next();
        });
    }
  };

  return {
    push(task) {
      pending.push(task);
      next();
      return () => {
        const index = pending.indexOf(task);
        if (index !== -1) pending.splice(index, 1);
      };
    },
  };
}
