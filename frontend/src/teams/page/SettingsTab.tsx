import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import teamsService, {
  memberTeamRole,
  teamErrorMessage,
  type TeamMember,
  type TeamRole,
} from '../../api/services/teamsService';
import { AGENTS_MANAGE_ROOT } from '../../agents/paths';
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { FormField } from '../../components/ui/form-field';
import { Input } from '../../components/ui/input';
import { SectionHeader } from '../../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Textarea } from '../../components/ui/textarea';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import { decodeJwtPayload } from '../../utils/jwtUtils';
import {
  loadWorkspaces,
  selectWorkspaceId,
  switchWorkspace,
} from '../../workspace/workspaceSlice';
import {
  deleteTeam,
  type DeleteTeamError,
  loadTeams,
  type Team,
} from '../teamsSlice';
import { truncateSub } from './teamGrants';
import { TEAMS_ROOT } from './teamTabs';

/** The kinds a refused delete names; anything else counts as "other". */
const ITEM_KINDS = [
  'agent',
  'workflow',
  'source',
  'tool',
  'prompt',
  'folder',
] as const;

/** The most members the transfer picker lists (the server's page limit). */
const TRANSFER_PAGE_SIZE = 100;

type SettingsTabProps = {
  team: Team;
  /** The caller's role in the team (owner or admin; others never see the tab). */
  role: TeamRole;
};

/**
 * The team's own settings: name and description for its admins; transfer
 * and delete for its owner. A team that still owns items can't be deleted:
 * the page says what it owns and offers to open the team to move them.
 */
export default function SettingsTab({ team, role }: SettingsTabProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectWorkspaceId);

  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [newOwner, setNewOwner] = useState('');
  const [transferState, setTransferState] = useState<ActiveState>('INACTIVE');

  const [deleteState, setDeleteState] = useState<ActiveState>('INACTIVE');
  const [notEmpty, setNotEmpty] = useState<Record<string, number> | null>(null);

  const currentUserId = useMemo(() => {
    const payload = token ? decodeJwtPayload(token) : null;
    return typeof payload?.sub === 'string' ? payload.sub : undefined;
  }, [token]);
  // Only the owner transfers or deletes. Older servers send no `is_owner`,
  // only `owner_id`.
  const isOwner =
    typeof team.is_owner === 'boolean'
      ? team.is_owner
      : role === 'owner' ||
        (Boolean(currentUserId) && team.owner_id === currentUserId);

  // Another team, or the same one renamed elsewhere: show what it says now.
  useEffect(() => {
    setName(team.name);
    setDescription(team.description ?? '');
  }, [team.id, team.name, team.description]);

  // Only the owner transfers, so only they need the member list.
  useEffect(() => {
    if (!isOwner) return;
    let cancelled = false;
    teamsService
      .listMembers(team.id, token, { page: 1, pageSize: TRANSFER_PAGE_SIZE })
      .then((r) => {
        if (!cancelled) setMembers(r?.members ?? []);
      })
      .catch(() => {
        // The picker stays empty; Transfer stays off.
      });
    return () => {
      cancelled = true;
    };
  }, [isOwner, team.id, token]);

  const memberLabel = (m: TeamMember): string =>
    m.email?.trim() || truncateSub(m.user_id);
  const candidates = members.filter(
    (m) => memberTeamRole(m) !== 'owner' && m.user_id !== currentUserId,
  );
  const newOwnerRow = candidates.find((m) => m.user_id === newOwner);

  const refreshTeams = () => {
    dispatch(loadTeams({ token }));
    dispatch(loadWorkspaces({ token }));
  };

  const dirty =
    name.trim() !== team.name ||
    description.trim() !== (team.description ?? '');

  const handleSave = async () => {
    if (!name.trim() || saving) return;
    setSaving(true);
    setSaveError(null);
    try {
      const res = await teamsService.update(
        team.id,
        { name: name.trim(), description: description.trim() },
        token,
      );
      if (!res || res.success === false) {
        setSaveError(res?.message ?? t('settings.teams.updateFailed'));
        return;
      }
      refreshTeams();
    } catch (error) {
      setSaveError(
        teamErrorMessage(t, error, t('settings.teams.updateFailed')),
      );
    } finally {
      setSaving(false);
    }
  };

  const confirmTransfer = async () => {
    await teamsService.transferOwner(team.id, newOwner, token);
    setNewOwner('');
    refreshTeams();
  };

  const confirmDelete = async () => {
    setNotEmpty(null);
    try {
      await dispatch(deleteTeam({ id: team.id, token })).unwrap();
    } catch (error) {
      const refused = error as DeleteTeamError | null;
      if (refused?.code === 'team_not_empty') {
        // Not a failure of the dialog: the page says what is left.
        setNotEmpty(refused.counts ?? {});
        return;
      }
      throw error;
    }
    navigate(TEAMS_ROOT);
  };

  // Moving or deleting the team's items happens inside the team.
  const openTeam = () => {
    navigate(AGENTS_MANAGE_ROOT);
    if (workspaceId !== team.id) dispatch(switchWorkspace(team.id));
  };

  const countLines = (counts: Record<string, number>): string[] => {
    const lines: string[] = [];
    let other = 0;
    Object.entries(counts).forEach(([kind, count]) => {
      if (!count) return;
      if (!(ITEM_KINDS as readonly string[]).includes(kind)) other += count;
    });
    ITEM_KINDS.forEach((kind) => {
      const count = counts[kind];
      if (count)
        lines.push(t(`settings.teams.notEmpty.counts.${kind}`, { count }));
    });
    if (other)
      lines.push(t('settings.teams.notEmpty.counts.other', { count: other }));
    return lines;
  };

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-4">
        <SectionHeader
          as="h4"
          size="sm"
          title={t('settings.teams.settingsTab.details')}
        />
        <FormField label={t('settings.teams.teamNamePlaceholder')}>
          <Input
            type="text"
            name="team-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
        <FormField label={t('settings.teams.descriptionLabel')}>
          <Textarea
            rows={3}
            resize="none"
            placeholder={t('settings.teams.descriptionPlaceholder')}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </FormField>
        {saveError && (
          <Alert variant="destructive">
            <AlertDescription>{saveError}</AlertDescription>
          </Alert>
        )}
        <div>
          <Button
            size="field"
            shape="pill"
            onClick={handleSave}
            disabled={!name.trim() || !dirty}
            loading={saving}
          >
            {t('settings.teams.save')}
          </Button>
        </div>
      </section>

      {isOwner && (
        <section className="border-border flex flex-col gap-4 border-t pt-6">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('settings.teams.transfer.title')}
            description={t('settings.teams.transfer.description')}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Select value={newOwner} onValueChange={setNewOwner}>
              <SelectTrigger
                className="w-full sm:w-72"
                aria-label={t('settings.teams.transfer.memberLabel')}
                disabled={candidates.length === 0}
              >
                <SelectValue
                  placeholder={t('settings.teams.transfer.placeholder')}
                />
              </SelectTrigger>
              <SelectContent capped>
                {candidates.map((m) => (
                  <SelectItem key={m.user_id} value={m.user_id}>
                    {memberLabel(m)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="field"
              shape="pill"
              disabled={!newOwnerRow}
              onClick={() => setTransferState('ACTIVE')}
            >
              {t('settings.teams.transfer.action')}
            </Button>
          </div>
        </section>
      )}

      {isOwner && (
        <section className="border-border flex flex-col gap-4 border-t pt-6">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('settings.teams.deleteTeam')}
            description={t('settings.teams.settingsTab.deleteHint')}
          />
          {notEmpty && (
            <Alert variant="warning">
              <AlertTitle>
                {t('settings.teams.notEmpty.title', {
                  interpolation: { escapeValue: false },
                  name: team.name,
                })}
              </AlertTitle>
              <AlertDescription>
                <ul className="list-inside list-disc">
                  {countLines(notEmpty).map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
                <p>
                  {t('settings.teams.notEmpty.hint')}{' '}
                  <AlertAction onClick={openTeam}>
                    {t('settings.teams.notEmpty.open', {
                      interpolation: { escapeValue: false },
                      name: team.name,
                    })}
                  </AlertAction>
                </p>
              </AlertDescription>
            </Alert>
          )}
          <div>
            <Button
              variant="destructive"
              size="field"
              shape="pill"
              onClick={() => setDeleteState('ACTIVE')}
            >
              {t('settings.teams.deleteTeam')}
            </Button>
          </div>
        </section>
      )}

      <ConfirmationModal
        message={t('settings.teams.transfer.confirm', {
          interpolation: { escapeValue: false },
          name: newOwnerRow ? memberLabel(newOwnerRow) : '',
          team: team.name,
        })}
        description={t('settings.teams.transfer.consequence')}
        modalState={transferState}
        setModalState={setTransferState}
        submitLabel={t('settings.teams.transfer.submit')}
        handleSubmit={confirmTransfer}
        error={(e) =>
          teamErrorMessage(t, e, t('settings.teams.transfer.error'))
        }
      />
      <ConfirmationModal
        message={t('settings.teams.deleteTeamConfirmation', {
          interpolation: { escapeValue: false },
          name: team.name,
        })}
        description={t('settings.teams.deleteTeamConsequence')}
        modalState={deleteState}
        setModalState={setDeleteState}
        submitLabel={t('settings.teams.delete')}
        handleSubmit={confirmDelete}
        error={(e) =>
          teamErrorMessage(t, e, t('settings.teams.deleteTeamError'))
        }
        variant="destructive"
      />
    </div>
  );
}
