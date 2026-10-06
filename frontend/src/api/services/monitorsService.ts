import apiClient from '../client';
import endpoints from '../endpoints';
import type { ApprovalView, Monitor } from '../../monitors/types';

/** A response's JSON body, or undefined when it has none (a proxy's HTML error page). */
const bodyOf = async <T>(response: Response): Promise<T | undefined> => {
  try {
    return (await response.json()) as T;
  } catch {
    return undefined;
  }
};

export type ApprovalResult =
  | { state: 'ok'; view: ApprovalView }
  | { state: 'missing' }
  | { state: 'error' };

export type DecisionResult =
  | { state: 'decided'; decision: string }
  | { state: 'already'; decision: string | null }
  | { state: 'missing' }
  | { state: 'limited' }
  | { state: 'invalid'; message: string }
  | { state: 'error' };

const monitorsService = {
  /** The public approval page's data. No token: the link's own token is the credential. */
  getApproval: async (linkToken: string): Promise<ApprovalResult> => {
    try {
      const r: Response = await apiClient.get(
        endpoints.USER.APPROVAL(linkToken),
        null,
      );
      if (r.status === 404) return { state: 'missing' };
      const view = r.ok ? await bodyOf<ApprovalView>(r) : undefined;
      return view ? { state: 'ok', view } : { state: 'error' };
    } catch {
      return { state: 'error' };
    }
  },

  /** Press a button on the approval page; only this ever decides. */
  decideApproval: async (
    linkToken: string,
    decision: string,
    comment: string,
  ): Promise<DecisionResult> => {
    try {
      const r: Response = await apiClient.post(
        endpoints.USER.APPROVAL(linkToken),
        comment.trim() ? { decision, comment: comment.trim() } : { decision },
        null,
      );
      const body = await bodyOf<{
        decision?: string | null;
        error?: string;
      }>(r);
      if (r.ok)
        return { state: 'decided', decision: body?.decision ?? decision };
      if (r.status === 409)
        return { state: 'already', decision: body?.decision ?? null };
      if (r.status === 404) return { state: 'missing' };
      if (r.status === 429) return { state: 'limited' };
      if (r.status === 400)
        return { state: 'invalid', message: body?.error ?? '' };
      return { state: 'error' };
    } catch {
      return { state: 'error' };
    }
  },

  /** The user's monitors (or one conversation's), newest first. */
  list: async (
    token: string | null,
    conversationId?: string,
  ): Promise<Monitor[]> => {
    const r: Response = await apiClient.get(
      endpoints.USER.MONITORS(conversationId),
      token,
    );
    if (!r.ok) throw new Error(`Listing monitors failed: ${r.status}`);
    const body = await bodyOf<{ monitors?: Monitor[] }>(r);
    return body?.monitors ?? [];
  },

  /** Pause, resume or cancel a monitor; resolves with the monitor after the change. */
  act: async (
    id: string,
    action: 'pause' | 'resume' | 'cancel',
    token: string | null,
  ): Promise<Monitor> => {
    const r: Response = await apiClient.post(
      endpoints.USER.MONITOR_ACTION(id, action),
      {},
      token,
    );
    const body = await bodyOf<{ monitor?: Monitor; message?: string }>(r);
    if (!r.ok || !body?.monitor) throw new Error(body?.message ?? '');
    return body.monitor;
  },
};

export default monitorsService;
