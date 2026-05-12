import { useDispatch, useSelector } from 'react-redux';
import { useMatch, useNavigate } from 'react-router-dom';

import WarnIcon from '../assets/warn.svg';
import type { RootState } from '../store';

import {
  dismissToolApproval,
  selectDismissedToolApprovals,
  selectRecentEvents,
} from './notificationsSlice';

/**
 * Surface ``tool.approval.required`` events as toasts that look like
 * ``UploadToast`` (same fixed bottom-right rail) — but only when the
 * user is NOT already on the conversation that needs the approval.
 *
 * - Dedup by ``conversation_id`` (the SSE ``scope.id``): keep only
 *   the newest pending event per conversation, so multiple paused
 *   tools in one conversation collapse to one toast.
 * - Dismissal is per-event-id so a *new* pause of the same
 *   conversation will re-surface (different event id).
 * - Clicking "Review" navigates to ``/c/<id>`` and dismisses.
 */
export default function ToolApprovalToast() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedToolApprovals);

  // Pull the active conversation id off the route. Two route shapes
  // place a conversation in view: the bare ``/c/:conversationId`` and
  // the agent-scoped ``/agents/:agentId/c/:conversationId``. Hooks
  // are unconditional; the toast just respects whichever matches.
  const plainMatch = useMatch('/c/:conversationId');
  const agentMatch = useMatch('/agents/:agentId/c/:conversationId');
  const currentConversationId =
    plainMatch?.params.conversationId ??
    agentMatch?.params.conversationId ??
    null;

  // Conversation name lookup — best-effort. The slice's
  // ``preference.conversations.data`` is populated by
  // ``useDataInitializer`` once auth resolves; until then we fall
  // back to the conversation id.
  const conversations = useSelector(
    (state: RootState) => state.preference.conversations.data,
  );

  const dismissedSet = new Set(dismissed);
  const pendingByConversation = new Map<
    string,
    { eventId: string; conversationId: string }
  >();
  for (const event of events) {
    if (event.type !== 'tool.approval.required') continue;
    if (!event.id) continue; // can't dismiss without an id
    if (dismissedSet.has(event.id)) continue;
    const conversationId = event.scope?.id;
    if (!conversationId) continue;
    if (currentConversationId && conversationId === currentConversationId) {
      continue;
    }
    if (pendingByConversation.has(conversationId)) continue;
    // ``recentEvents`` is newest-first, so the first match per convId
    // is the most recent unhandled approval.
    pendingByConversation.set(conversationId, {
      eventId: event.id,
      conversationId,
    });
  }

  if (pendingByConversation.size === 0) return null;

  const conversationName = (conversationId: string): string => {
    const found = conversations?.find((c) => c.id === conversationId);
    return found?.name ?? 'Conversation';
  };

  return (
    // Sit above ``UploadToast`` (which owns ``bottom-4 right-4``)
    // rather than overlapping it. ``bottom-24`` ≈ 96px clears one
    // standard-height upload toast; multiple in-flight uploads will
    // stack into the gap, at which point the approval toast still
    // floats on top via ``z-50``. Acceptable v1 layout — the two
    // surfaces are rarely competing.
    <div
      className="fixed right-4 bottom-24 z-50 flex max-w-md flex-col gap-2"
      onMouseDown={(e) => e.stopPropagation()}
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {Array.from(pendingByConversation.values()).map(
        ({ eventId, conversationId }) => (
          <div
            key={eventId}
            className="border-border bg-card w-[271px] overflow-hidden rounded-2xl border shadow-[0px_24px_48px_0px_#00000029]"
          >
            <div className="bg-accent/50 dark:bg-muted flex items-center justify-between px-4 py-3">
              <h3 className="font-inter dark:text-foreground text-[14px] leading-[16.5px] font-medium text-black">
                Tool approval needed
              </h3>
              <button
                type="button"
                onClick={() => dispatch(dismissToolApproval(eventId))}
                className="flex h-8 items-center justify-center p-0 text-black opacity-70 transition-opacity hover:opacity-100 dark:text-white"
                aria-label="Dismiss"
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className="h-4 w-4"
                >
                  <path
                    d="M18 6L6 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M6 6L18 18"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
            <div className="flex items-center justify-between gap-3 px-5 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <img
                  src={WarnIcon}
                  alt=""
                  className="h-5 w-5 shrink-0"
                  aria-hidden="true"
                />
                <p
                  className="font-inter dark:text-muted-foreground max-w-[140px] truncate text-[13px] leading-[16.5px] font-normal text-black"
                  title={conversationName(conversationId)}
                >
                  {conversationName(conversationId)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  dispatch(dismissToolApproval(eventId));
                  navigate(`/c/${conversationId}`);
                }}
                className="rounded-full bg-[#7D54D1] px-3 py-1 text-[12px] font-medium text-white shadow-sm hover:bg-[#6a45b8]"
              >
                Review
              </button>
            </div>
          </div>
        ),
      )}
    </div>
  );
}
