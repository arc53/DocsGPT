// How long an attachment upload may go without any sign of life. It is an
// idle window, not a total cap: a large file on a slow link keeps resetting
// it with progress events, so only a silent stall is cut off.
export const UPLOAD_STALL_TIMEOUT_MS = 120_000;

/**
 * Abort ``xhr`` once it makes no progress for ``idleMs``.
 *
 * ``xhr.timeout`` would cap the whole request, which a large file on a slow
 * connection can legitimately exceed. This resets on every upload progress
 * event, and again when the body finishes sending so the server gets its own
 * window to answer. The abort fires the request's ``onabort`` handler, which
 * is where the caller marks the attachment failed.
 *
 * Args:
 *   xhr: The request to watch. Call before ``send()``.
 *   idleMs: The longest allowed gap between signs of progress.
 */
export function guardUploadStall(
  xhr: XMLHttpRequest,
  idleMs: number = UPLOAD_STALL_TIMEOUT_MS,
): void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const restart = () => {
    clearTimeout(timer);
    timer = setTimeout(() => xhr.abort(), idleMs);
  };
  xhr.upload.addEventListener('progress', restart);
  xhr.upload.addEventListener('load', restart);
  xhr.addEventListener('progress', restart);
  xhr.addEventListener('loadend', () => clearTimeout(timer));
  restart();
}
