/**
 * A non-2xx API answer: `status` is the HTTP status, `code` the server's
 * stable `error` code when it sent one, `message` its own text (or a generic
 * line), `body` the whole parsed answer. A service subclasses it so callers
 * can tell whose call failed; the subclass sets `name` itself, because a
 * thunk's `unwrap` keeps only plain fields and callers match on the name.
 */
export class ApiError extends Error {
  status: number;
  code?: string;
  body?: Record<string, unknown>;

  constructor(
    status: number,
    message: string,
    code?: string,
    body?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

/** What a refused answer said: each part only when the server sent it. */
export type ApiRefusal = {
  code?: string;
  message?: string;
  body?: Record<string, unknown>;
};

/**
 * Reads a refused answer's JSON for its `error` code, its `message` and the
 * whole body. An answer that isn't JSON (a proxy's page, a bare 404) yields
 * nothing, so the caller falls back to the status.
 *
 * Args:
 *   response: The non-2xx response; its body is consumed.
 *
 * Returns:
 *   The parts the server sent.
 */
export async function readRefusal(response: Response): Promise<ApiRefusal> {
  const refusal: ApiRefusal = {};
  try {
    const parsed = await response.json();
    if (parsed && typeof parsed === 'object') refusal.body = parsed;
    if (typeof parsed?.error === 'string' && parsed.error)
      refusal.code = parsed.error;
    if (typeof parsed?.message === 'string' && parsed.message)
      refusal.message = parsed.message;
  } catch {
    // Not JSON: the status is all there is.
  }
  return refusal;
}

/** The generic message of a refusal that said nothing usable. */
export const requestFailed = (status: number): string =>
  `Request failed (${status})`;

/**
 * The error a refused answer throws, as `ErrorClass`: the server's message,
 * else (with `codeAsMessage`) its code, else a generic line naming the status.
 *
 * Args:
 *   response: The non-2xx response; its body is consumed.
 *   ErrorClass: The service's subclass of `ApiError`.
 *   options: `codeAsMessage` uses the code when the server sent no message.
 *
 * Returns:
 *   The error to throw.
 */
export async function apiErrorFrom<E extends ApiError>(
  response: Response,
  ErrorClass: new (...args: ConstructorParameters<typeof ApiError>) => E,
  { codeAsMessage = false }: { codeAsMessage?: boolean } = {},
): Promise<E> {
  const { code, message, body } = await readRefusal(response);
  return new ErrorClass(
    response.status,
    message ??
      (codeAsMessage ? code : undefined) ??
      requestFailed(response.status),
    code,
    body,
  );
}
