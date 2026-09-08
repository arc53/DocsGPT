/**
 * `/api/store_attachment` returns a Celery task id; the parsed attachment
 * only exists once that task lands, hence the polling below. The id `/stream`
 * expects is the task result's `attachment_id`, not the one the upload
 * response carries. Auth is the agent key as `api_key` in the multipart body.
 */

interface UploadAttachmentOptions {
  file: File;
  apiKey: string;
  apiHost: string;
  onProgress?: (percent: number) => void;
  signal?: AbortSignal;
}

export interface UploadedAttachment {
  taskId: string;
}

export type TaskOutcome =
  | { state: 'pending' }
  | { state: 'completed'; attachmentId?: string }
  | { state: 'failed' };

/** The route composes these itself (too large, unsupported type), so they are safe to show. */
const errorMessageFrom = (body: string): string | undefined => {
  try {
    const parsed = JSON.parse(body);
    const message = parsed?.errors?.[0]?.error ?? parsed?.message;
    return typeof message === 'string' && message ? message : undefined;
  } catch {
    return undefined;
  }
};

export function uploadAttachment({
  file,
  apiKey,
  apiHost,
  onProgress,
  signal,
}: UploadAttachmentOptions): Promise<UploadedAttachment> {
  return new Promise<UploadedAttachment>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Upload aborted', 'AbortError'));
      return;
    }

    const formData = new FormData();
    formData.append('file', file);
    if (apiKey) formData.append('api_key', apiKey);

    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    signal?.addEventListener('abort', onAbort, { once: true });

    // fetch cannot report upload progress.
    xhr.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable)
        onProgress?.(Math.round((event.loaded / event.total) * 100));
    });

    xhr.onload = () => {
      signal?.removeEventListener('abort', onAbort);
      const fallback = errorMessageFrom(xhr.responseText);
      if (xhr.status !== 200) {
        reject(new Error(fallback ?? 'Upload failed.'));
        return;
      }
      try {
        const response = JSON.parse(xhr.responseText);
        // One file answers with a bare `task_id`; the batch shape is read
        // too, in case the route stops special-casing one file.
        const task = response?.task_id ? response : response?.tasks?.[0];
        if (!task?.task_id) {
          reject(new Error(fallback ?? 'Upload failed.'));
          return;
        }
        resolve({ taskId: task.task_id });
      } catch {
        reject(new Error('Upload failed.'));
      }
    };

    xhr.onerror = () => {
      signal?.removeEventListener('abort', onAbort);
      reject(new Error('Upload failed.'));
    };
    xhr.onabort = () => {
      signal?.removeEventListener('abort', onAbort);
      reject(new DOMException('Upload aborted', 'AbortError'));
    };

    xhr.open('POST', `${apiHost}/api/store_attachment`);
    xhr.send(formData);
  });
}

/**
 * A 503 or transport failure reads as `pending`: the worker fleet is
 * unreachable, which says nothing about this file.
 *
 * A failed task's `result` is the raw exception, which has no business on a
 * third-party page, so no reason is returned and the caller supplies one.
 */
export async function fetchTaskOutcome(
  taskId: string,
  apiHost: string,
  signal?: AbortSignal,
): Promise<TaskOutcome> {
  const response = await fetch(
    `${apiHost}/api/task_status?task_id=${encodeURIComponent(taskId)}`,
    { signal },
  );
  if (!response.ok) return { state: 'pending' };

  const data = await response.json().catch(() => null);
  if (data?.status === 'SUCCESS') {
    const attachmentId = data?.result?.attachment_id;
    return {
      state: 'completed',
      attachmentId: attachmentId ? String(attachmentId) : undefined,
    };
  }
  if (data?.status === 'FAILURE' || data?.status === 'REVOKED')
    return { state: 'failed' };
  return { state: 'pending' };
}
