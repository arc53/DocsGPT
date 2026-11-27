import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import type { AppDispatch, RootState } from '../store';
import { selectTurnToolCalls, setToolDecision } from './conversationSlice';
import type { ToolCallsType } from './types';

/**
 * The cards still undecided in the turn holding ``callId``. One resume
 * settles every waiting call of a turn, so a decision is held until each card
 * has one (see ``decideToolCall``).
 *
 * Returns:
 *   ``undecided``: the approval and Connect cards with no decision yet;
 *   ``approvable``: those of them Approve all can decide (not Connect cards,
 *   which wait on an account).
 */
export function useTurnApprovals(callId: string): {
  undecided: number;
  approvable: number;
} {
  const calls = useSelector((state: RootState) =>
    selectTurnToolCalls(state, callId),
  );
  const undecided = calls.filter(
    (call) => call.status === 'awaiting_approval' && !call.local_decision,
  );
  return {
    undecided: undecided.length,
    approvable: undecided.filter((call) => !call.connection_required).length,
  };
}

/** The state Badge of a card whose decision is held. */
export function HeldDecisionBadge({
  decision,
}: {
  decision: NonNullable<ToolCallsType['local_decision']>;
}) {
  const { t } = useTranslation();
  const approved = decision.decision === 'approved';
  return (
    <Badge variant={approved ? 'success' : 'destructive'}>
      {t(
        approved
          ? 'conversation.toolApproval.state.approved'
          : 'conversation.toolApproval.state.denied',
      )}
    </Badge>
  );
}

/**
 * Takes a held decision back, so the card asks again. A card shows none once
 * its decision is sent: the request is open, and a second would replace it.
 */
export function UndoDecisionButton({ callId }: { callId: string }) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      shape="pill"
      onClick={() => dispatch(setToolDecision({ callId, decision: null }))}
    >
      {t('conversation.toolApproval.undo')}
    </Button>
  );
}

/** Says why a decided card has not resumed the turn yet. */
export function WaitingForOthersNote() {
  const { t } = useTranslation();
  return (
    <p className="text-muted-foreground text-xs">
      {t('conversation.toolApproval.waitingForOthers')}
    </p>
  );
}
