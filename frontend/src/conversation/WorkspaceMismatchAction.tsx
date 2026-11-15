import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import { agentChatPath } from '../agents/paths';
import { AlertAction } from '../components/ui/alert';
import {
  selectAgents,
  selectSelectedAgent,
  selectSharedAgents,
} from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import type { AccessFields } from '../utils/accessUtils';
import { switchWorkspace } from '../workspace/workspaceSlice';
import { followStep } from './followWorkspace';

/**
 * The fix under a chat refused because its agent lives in another workspace
 * than the chat: "Switch to <workspace>", which goes there and opens a new
 * chat with the agent (a chat keeps the workspace it was started in, so the
 * old one can't take the agent). Nothing when the caller isn't in the
 * agent's workspace or the agent isn't known here.
 *
 * Args:
 *   agentId: The chat's agent.
 */
export default function WorkspaceMismatchAction({
  agentId,
}: {
  agentId?: string;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const selectedAgent = useSelector(selectSelectedAgent);
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const agent = agentId
    ? [
        ...(selectedAgent ? [selectedAgent] : []),
        ...(agents ?? []),
        ...(sharedAgents ?? []),
      ].find((candidate) => candidate.id === agentId)
    : undefined;
  const workspace = useSelector((state: RootState) => state.workspace);
  const step = followStep(
    (agent as AccessFields | undefined)?.workspace,
    workspace,
  );

  if (!agentId || step.kind !== 'switch') return null;
  return (
    <AlertAction
      onClick={() => {
        // Leave the old chat in the same render as the switch, so the page
        // that reloads is the agent's new chat.
        navigate(agentChatPath(agentId));
        dispatch(switchWorkspace(step.target, { reason: 'link' }));
      }}
    >
      {t('workspace.chat.switchTo', {
        name: step.name,
        interpolation: { escapeValue: false },
      })}
    </AlertAction>
  );
}
