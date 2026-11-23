/**
 * The workspace every request is sent for, kept outside the store so the API
 * client can read it without importing the store. The workspace listener
 * keeps it in step with the `workspace` slice; nothing else should set it.
 */

/** The header that names the workspace a list or a create is for. */
export const WORKSPACE_HEADER = 'X-DocsGPT-Workspace';

/** The id of the caller's own workspace. */
export const PERSONAL_WORKSPACE = 'personal';

let current = { id: PERSONAL_WORKSPACE, epoch: 0 };

type WorkspaceHandler = (workspace: string) => void;
const lostHandlers = new Set<WorkspaceHandler>();
const roleRefusedHandlers = new Set<WorkspaceHandler>();

/**
 * Sets the workspace requests are sent for.
 *
 * Args:
 *   id: `personal` or a team id.
 *   epoch: The slice's switch counter, so an answer captured before a switch
 *     away and back still reads as stale.
 */
export function setRequestWorkspace(id: string, epoch: number): void {
  current = { id, epoch };
}

/** The workspace requests are sent for now: `personal` or a team id. */
export function requestWorkspace(): string {
  return current.id;
}

/** A workspace taken when a request goes out, to check when it answers. */
export type CapturedWorkspace = {
  id: string;
  epoch: number;
  /** False once the app has switched since (even away and back). */
  isCurrent: () => boolean;
};

/**
 * Takes the current workspace before a request, so its answer can be dropped
 * when the user switched while it was out (a slow Personal list must not land
 * in a team).
 *
 * Returns:
 *   The id and switch epoch, with `isCurrent()` to test them later.
 */
export function captureWorkspace(): CapturedWorkspace {
  const { id, epoch } = current;
  return {
    id,
    epoch,
    isCurrent: () => current.id === id && current.epoch === epoch,
  };
}

/**
 * The workspace header, for a request that sets its own headers (an XHR) or
 * one that must go to another workspace than the current one.
 *
 * Args:
 *   id: The workspace to name; the current one when left out.
 *
 * Returns:
 *   `{ 'X-DocsGPT-Workspace': id }`.
 */
export function workspaceHeader(id?: string): Record<string, string> {
  return { [WORKSPACE_HEADER]: id ?? current.id };
}

const subscribe = (
  handlers: Set<WorkspaceHandler>,
  handler: WorkspaceHandler,
): (() => void) => {
  handlers.add(handler);
  return () => {
    handlers.delete(handler);
  };
};

/**
 * Calls `handler` with the workspace a request was sent for when the server
 * answers 404 `workspace_not_found` (the caller left the team, or it was
 * deleted).
 *
 * Returns:
 *   A function that removes the handler.
 */
export function onWorkspaceLost(handler: WorkspaceHandler): () => void {
  return subscribe(lostHandlers, handler);
}

/**
 * Calls `handler` with the workspace a request was sent for when the server
 * answers 403 `workspace_role_required` (the caller's role there changed).
 *
 * Returns:
 *   A function that removes the handler.
 */
export function onWorkspaceRoleRefused(handler: WorkspaceHandler): () => void {
  return subscribe(roleRefusedHandlers, handler);
}

/**
 * Reports a workspace refusal the API client read from a response body.
 *
 * Args:
 *   status: The response's HTTP status.
 *   error: The body's `error` code.
 *   workspace: The workspace header the request was sent with.
 */
export function reportWorkspaceRefusal(
  status: number,
  error: unknown,
  workspace: string,
): void {
  const handlers =
    status === 404 && error === 'workspace_not_found'
      ? lostHandlers
      : status === 403 && error === 'workspace_role_required'
        ? roleRefusedHandlers
        : null;
  handlers?.forEach((handler) => handler(workspace));
}
