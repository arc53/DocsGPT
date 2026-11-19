import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import customModelsService from '../api/services/customModelsService';
import { FormField } from '../components/ui/form-field';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import ConfirmationModal from '../modals/ConfirmationModal';
import { customModelRequestError } from '../models/customModelErrors';
import type { CustomModel } from '../models/types';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import {
  roleAtLeast,
  type WorkspaceRow,
  type WorkspaceState,
} from '../workspace/workspaceSlice';

const noEscape = { interpolation: { escapeValue: false } };
const NO_WORKSPACES: WorkspaceRow[] = [];

// Settings pages also render in tests whose store has no workspace slice;
// such a store has no teams.
const selectWorkspaceRows = (state: {
  workspace?: WorkspaceState;
}): WorkspaceRow[] => state.workspace?.workspaces ?? NO_WORKSPACES;

/**
 * The teams the reader may copy a model into: those where they are an Admin
 * or the Owner, as the workspace switcher lists them.
 *
 * Args:
 *   workspaces: The reader's workspaces, with their role in each team.
 *
 * Returns:
 *   The team rows.
 */
export const copyTargets = (workspaces: WorkspaceRow[]): WorkspaceRow[] =>
  workspaces.filter(
    (row) => row.kind === 'team' && roleAtLeast(row.role, 'admin'),
  );

/** The teams the reader may copy a model into, from the store. */
export function useCopyTargets(): WorkspaceRow[] {
  const workspaces = useSelector(selectWorkspaceRows);
  return useMemo(() => copyTargets(workspaces), [workspaces]);
}

/**
 * "Copy to a team" for one of the reader's own models: the team gets its own
 * copy with the same key, and the reader's model stays as it is. With more
 * than one team the reader picks which; a refusal (the team already has the
 * model, the key can't be read) stays in the dialog.
 *
 * Args:
 *   model: The model to copy; null closes the dialog.
 *   teams: The teams the reader may copy into.
 *   onClose: Called when the dialog closes.
 */
export default function CopyModelToTeamModal({
  model,
  teams,
  onClose,
}: {
  model: CustomModel | null;
  teams: WorkspaceRow[];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  // Null until the reader picks one: the first team.
  const [teamId, setTeamId] = useState<string | null>(null);
  const close = () => {
    setTeamId(null);
    onClose();
  };

  const team = teams.find((row) => row.id === teamId) ?? teams[0];
  const name = model?.display_name ?? '';

  const copy = async () => {
    if (!model || !team) return;
    await customModelsService.copyToTeam(model.id, team.id, token);
    dispatch(
      showActionToast({
        variant: 'success',
        message: t('settings.customModels.team.copy.done', {
          name,
          team: team.name,
          ...noEscape,
        }),
      }),
    );
  };

  return (
    <ConfirmationModal
      message={t('settings.customModels.team.copy.title')}
      description={
        teams.length > 1
          ? t('settings.customModels.team.copy.body', { name, ...noEscape })
          : t('settings.customModels.team.copy.bodyTo', {
              name,
              team: team?.name ?? '',
              ...noEscape,
            })
      }
      modalState={model ? 'ACTIVE' : 'INACTIVE'}
      setModalState={(state) => state === 'INACTIVE' && close()}
      submitLabel={t('settings.customModels.team.copy.confirm')}
      handleSubmit={copy}
      error={(reason) =>
        customModelRequestError(t, reason, t('common.actionFailed'))
      }
    >
      {teams.length > 1 ? (
        <FormField label={t('settings.customModels.team.copy.team')}>
          <Select value={team?.id} onValueChange={setTeamId}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {teams.map((row) => (
                <SelectItem key={row.id} value={row.id}>
                  {row.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      ) : null}
    </ConfirmationModal>
  );
}
