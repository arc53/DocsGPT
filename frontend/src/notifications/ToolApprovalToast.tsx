import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useMatch, useNavigate } from 'react-router-dom';

import { Button } from '../components/ui/button';
import {
  Toast,
  ToastActions,
  ToastContent,
  ToastHeader,
  ToastItem,
  ToastStatus,
  ToastTitle,
} from '../components/ui/toast';
import type { RootState } from '../store';

import {
  dismissToolApproval,
  selectDismissedToolApprovals,
  selectRecentEvents,
} from './notificationsSlice';

// Backend ``PENDING_STATE_TTL_SECONDS`` is 30 min; allow a margin for
// clock skew before treating a still-present approval event as moot.
const APPROVAL_EVENT_MAX_AGE_MS = 35 * 60 * 1000;

/**
 * Surface ``tool.approval.required`` events as toast cards in the shared
 * ``ToastViewport`` (mounted in App.tsx, between the team notifications
 * and ``UploadToast``) — but only when the user is NOT already on the
 * conversation that needs the approval.
 *
 * - Dedup by ``conversation_id`` (the SSE ``scope.id``): keep only
 *   the newest pending event per conversation, so multiple paused
 *   tools in one conversation collapse to one toast.
 * - Dismissal is per-event-id so a *new* pause of the same
 *   conversation will re-surface (different event id).
 * - Clicking "Review" navigates to ``/c/<id>`` and dismisses.
 */
export default function ToolApprovalToast() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const events = useSelector(selectRecentEvents);
  const dismissed = useSelector(selectDismissedToolApprovals);

  // Pull the active conversation id off the route. Two route shapes
  // place a conversation in view: the bare ``/c/:conversationId`` and
  // the agent-scoped ``/agents/:agentId/c/:conversationId``. Hooks
  // are unconditional; the toast just respects whichever matches.
  //
  // ``/c/new`` is the conversation route's literal-string placeholder
  // for "unknown / not-yet-loaded conversation" (see the rewrite in
  // the conversation route). Treat it the same as no match — the
  // user isn't viewing any specific conversation yet, so an approval
  // toast for any conversation should still surface.
  const plainMatch = useMatch('/c/:conversationId');
  const agentMatch = useMatch('/agents/:agentId/c/:conversationId');
  const matchedConversationId =
    plainMatch?.params.conversationId ??
    agentMatch?.params.conversationId ??
    null;
  const currentConversationId =
    matchedConversationId === 'new' ? null : matchedConversationId;

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
  const now = Date.now();
  for (const event of events) {
    if (event.type !== 'tool.approval.required') continue;
    if (!event.id) continue; // can't dismiss without an id
    if (dismissedSet.has(event.id)) continue;
    // Timestamp backstop: an approval is only resumable inside the
    // backend pending-tool-state TTL. Past that window the prompt is
    // moot, so don't surface it even if no clearing event arrived (lost
    // publish, older backend). Keyed off the envelope's own ``ts`` so it
    // holds across reload/backlog replay.
    if (event.ts) {
      const age = now - Date.parse(event.ts);
      if (Number.isFinite(age) && age > APPROVAL_EVENT_MAX_AGE_MS) continue;
    }
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
    return found?.name ?? t('notifications.toolApprovalFallbackName');
  };

  return (
    <>
      {Array.from(pendingByConversation.values()).map(
        ({ eventId, conversationId }) => (
          <Toast key={eventId}>
            <ToastHeader variant="warning">
              <ToastTitle>{t('notifications.toolApprovalTitle')}</ToastTitle>
              <ToastActions>
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="icon-sm"
                  onClick={() => dispatch(dismissToolApproval(eventId))}
                  aria-label={t('notifications.dismiss')}
                >
                  <X />
                </Button>
              </ToastActions>
            </ToastHeader>
            <ToastContent>
              <ToastItem
                icon={<ToastStatus status="warning" />}
                label={
                  <span title={conversationName(conversationId)}>
                    {conversationName(conversationId)}
                  </span>
                }
              >
                <Button
                  type="button"
                  size="xs"
                  shape="pill"
                  onClick={() => {
                    dispatch(dismissToolApproval(eventId));
                    navigate(`/c/${conversationId}`);
                  }}
                >
                  {t('notifications.toolApprovalReview')}
                </Button>
              </ToastItem>
            </ToastContent>
          </Toast>
        ),
      )}
    </>
  );
}
