import { Link, Trash2, Users } from 'lucide-react';
import { type ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../../api/services/userService';
import { ActionMenu, type MenuOption } from '@/components/ui/dropdown-menu';
import AgentDetailsModal from '../../modals/AgentDetailsModal';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import ShareToTeamModal from '../../teams/ShareToTeamModal';
import { can } from '../../utils/accessUtils';
import { agentsListPath } from '../paths';
import type { Agent, AgentConfig } from '../types';

type UseAgentMenuOptions = {
  /** The agent the menu acts on; nothing is offered until it has an id. */
  agent: Agent | null | undefined;
  /** Page items before the agent's own (Overview's Preview while a draft). */
  lead?: MenuOption[];
  /**
   * Whether Access details and Share are offered; defaults to a saved,
   * non-draft agent. Overview passes its form mode.
   */
  shareable?: boolean;
  /**
   * Opens a page's own Access details (Overview's, tied to its form). Without
   * it the menu draws a plain AgentDetailsModal. `apiWrites` opens it on the
   * API writes allowlist (from the Share dialog's link).
   */
  openAccessDetails?: (apiWrites: boolean) => void;
  /** After a delete; defaults to the agent list. */
  onDeleted?: () => void;
  /** A key regenerated in the menu's own Access details. */
  onKeyRegenerated?: (key: string) => void;
  /**
   * The config the menu's own Access details saved (its write allowlist).
   * The page puts it on `agent`, which the dialog reopens from.
   */
  onConfigChange?: (config: AgentConfig) => void;
};

/**
 * The agent's ⋯ for its pages' toolbar row (`AgentPageToolbar menu`):
 * the page's lead items, Access details and Share with team (each when the
 * role allows it), then Delete set apart by a rule, with the dialogs they open.
 *
 * Args:
 *   options: See UseAgentMenuOptions.
 *
 * Returns:
 *   `menu`, the ⋯ (null with no items), and `modals`, to render once.
 */
export function useAgentMenu({
  agent,
  lead = [],
  shareable,
  openAccessDetails,
  onDeleted,
  onKeyRegenerated,
  onConfigChange,
}: UseAgentMenuOptions): { menu: ReactNode; modals: ReactNode } {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const [details, setDetails] = useState<ActiveState>('INACTIVE');
  const [detailsOnApiWrites, setDetailsOnApiWrites] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteState, setDeleteState] = useState<ActiveState>('INACTIVE');
  const [deleteError, setDeleteError] = useState<string>();

  const saved = Boolean(agent?.id);
  const offerSharing = saved && (shareable ?? agent?.status !== 'draft');
  const canAccessDetails = offerSharing && can(agent, 'manage_access_details');
  const showAccessDetails = (apiWrites: boolean) => {
    if (openAccessDetails) {
      openAccessDetails(apiWrites);
      return;
    }
    setDetailsOnApiWrites(apiWrites);
    setDetails('ACTIVE');
  };

  const options: MenuOption[] = [
    ...lead,
    ...(canAccessDetails
      ? [
          {
            label: t('agents.form.buttons.accessDetails'),
            icon: Link,
            onClick: () => showAccessDetails(false),
          },
        ]
      : []),
    // Sharing is the owner's, unless the owner lets editors share.
    ...(offerSharing && can(agent, 'share')
      ? [
          {
            label: t('agents.shareWithTeam'),
            icon: Users,
            onClick: () => setShareOpen(true),
          },
        ]
      : []),
    ...(saved && can(agent, 'delete')
      ? [
          {
            label: t('agents.form.buttons.delete'),
            icon: Trash2,
            variant: 'destructive' as const,
            separatorBefore: true,
            onClick: () => setDeleteState('ACTIVE'),
          },
        ]
      : []),
  ];

  // Returned to ConfirmationModal: it stays pending while this runs and
  // keeps a failure in the dialog (the server's message when it gives one).
  const handleDelete = async () => {
    setDeleteError(undefined);
    const response = await userService.deleteAgent(agent?.id ?? '', token);
    if (!response.ok) {
      const message = await response
        .json()
        .then((data: { message?: string }) => data?.message)
        .catch(() => null);
      setDeleteError(message || undefined);
      throw new Error(message || 'Failed to delete agent');
    }
    if (onDeleted) onDeleted();
    else navigate(agentsListPath());
  };

  const menu =
    options.length > 0 ? (
      <ActionMenu
        size="toolbar"
        triggerLabel={t('agents.form.buttons.moreActions')}
        options={options}
      />
    ) : null;

  const modals =
    agent && saved ? (
      <>
        <ConfirmationModal
          message={t('agents.deleteConfirmation', {
            interpolation: { escapeValue: false },
            name: agent.name,
          })}
          description={t('agents.deleteConsequence')}
          modalState={deleteState}
          setModalState={setDeleteState}
          submitLabel={t('agents.form.buttons.delete')}
          handleSubmit={handleDelete}
          error={deleteError ?? t('agents.deleteFailed')}
          cancelLabel={t('agents.form.buttons.cancel')}
          variant="destructive"
        />
        {!openAccessDetails && canAccessDetails && (
          <AgentDetailsModal
            agent={agent}
            mode="edit"
            modalState={details}
            setModalState={(state) => {
              setDetails(state);
              if (state === 'INACTIVE') setDetailsOnApiWrites(false);
            }}
            openApiWrites={detailsOnApiWrites}
            onKeyRegenerated={onKeyRegenerated}
            onConfigChange={onConfigChange}
          />
        )}
        {shareOpen && agent.id && (
          <ShareToTeamModal
            resourceType="agent"
            resourceId={agent.id}
            resourceName={agent.name}
            onClose={() => setShareOpen(false)}
            onOpenAccessDetails={
              canAccessDetails
                ? () => {
                    setShareOpen(false);
                    showAccessDetails(true);
                  }
                : undefined
            }
          />
        )}
      </>
    ) : null;

  return { menu, modals };
}
