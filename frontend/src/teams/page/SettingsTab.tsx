import { FileDown } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import teamsService, {
  isOutsidePolicy,
  memberTeamRole,
  OUTSIDE_POLICIES,
  type OutsidePolicy,
  teamErrorMessage,
  type TeamMember,
  type TeamOutside,
  type TeamRole,
} from '../../api/services/teamsService';
import { AGENTS_MANAGE_ROOT } from '../../agents/paths';
import payerService, {
  payerErrorMessage,
} from '../../api/services/payerService';
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from '../../components/ui/alert';
import { Button } from '../../components/ui/button';
import { Combobox } from '../../components/ui/combobox';
import { FormField } from '../../components/ui/form-field';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { RadioGroup, RadioGroupItem } from '../../components/ui/radio-group';
import { SectionHeader } from '../../components/ui/section-header';
import { Textarea } from '../../components/ui/textarea';
import { useDebouncedValue } from '../../hooks';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { ActiveState } from '../../models/misc';
import { showActionToast } from '../../notifications/actionToastSlice';
import { selectToken } from '../../preferences/preferenceSlice';
import { AppDispatch } from '../../store';
import { downloadBlob } from '../../utils/browserUtils';
import { decodeJwtPayload } from '../../utils/jwtUtils';
import {
  loadWorkspaces,
  roleAtLeast,
  selectWorkspaceId,
  selectWorkspaces,
  switchWorkspace,
} from '../../workspace/workspaceSlice';
import {
  deleteTeam,
  type DeleteTeamError,
  loadTeams,
  setTeamOutsidePolicy,
  type Team,
} from '../teamsSlice';
import OutsidePolicyConfirm from './OutsidePolicyConfirm';
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
  'connection',
] as const;

/** Where a team Admin removes the team's connections. */
const CONNECTORS_PATH = '/settings/connectors';

/**
 * The most members one answer of the transfer picker lists (the server's
 * page limit); the picker searches the server for the rest.
 */
const TRANSFER_PAGE_SIZE = 100;

/** Whom the team can go to: anyone but its owner (the caller). */
const isTransferCandidate = (m: TeamMember, me?: string): boolean =>
  memberTeamRole(m) !== 'owner' && m.user_id !== me;

type SettingsTabProps = {
  team: Team;
  /** The caller's role in the team (owner or admin; others never see the tab). */
  role: TeamRole;
};

/**
 * The team's own settings: name and description for its admins, who may
 * take the team's items outside, and the chat export when the instance
 * allows it; transfer and delete for its owner. A team that still owns items can't be deleted: the page says what
 * it owns and offers to open the team to move them.
 */
export default function SettingsTab({ team, role }: SettingsTabProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const workspaceId = useSelector(selectWorkspaceId);
  const workspaces = useSelector(selectWorkspaces);
  // The instance setting comes on the team's workspace row.
  const chatExport =
    roleAtLeast(role, 'admin') &&
    workspaces.some((row) => row.id === team.id && row.chat_export === true);
  const [exporting, setExporting] = useState(false);

  const [name, setName] = useState(team.name);
  const [description, setDescription] = useState(team.description ?? '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [members, setMembers] = useState<TeamMember[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  // Whether the team has anyone to hand it to, from the unsearched list.
  const [hasCandidates, setHasCandidates] = useState(false);
  const [memberQuery, setMemberQuery] = useState('');
  const debouncedQuery = useDebouncedValue(memberQuery.trim(), 250);
  const [newOwnerRow, setNewOwnerRow] = useState<TeamMember | null>(null);
  const [transferState, setTransferState] = useState<ActiveState>('INACTIVE');

  // The policy picked and waiting on its confirm, and what the team has
  // outside (the confirm counts it).
  const [policyPick, setPolicyPick] = useState<OutsidePolicy | null>(null);
  const [outside, setOutside] = useState<TeamOutside | null>(null);

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

  // Only the owner transfers, so only they need the member list. The server
  // searches it, so a member past the first page is found by name.
  useEffect(() => {
    if (!isOwner) return;
    let cancelled = false;
    setMembersLoading(true);
    teamsService
      .listMembers(team.id, token, {
        q: debouncedQuery || undefined,
        page: 1,
        pageSize: TRANSFER_PAGE_SIZE,
      })
      .then((r) => {
        if (cancelled) return;
        const rows: TeamMember[] = r?.members ?? [];
        setMembers(rows);
        if (!debouncedQuery)
          setHasCandidates(
            rows.some((m) => isTransferCandidate(m, currentUserId)),
          );
      })
      .catch(() => {
        // The picker stays empty; Transfer stays off.
        if (!cancelled) setMembers([]);
      })
      .finally(() => {
        if (!cancelled) setMembersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOwner, team.id, token, debouncedQuery, currentUserId]);

  const memberLabel = (m: TeamMember): string =>
    m.email?.trim() || truncateSub(m.user_id);
  const candidates = members.filter((m) =>
    isTransferCandidate(m, currentUserId),
  );

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

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const { blob, filename } = await payerService.exportTeamChats(
        team.id,
        token,
      );
      downloadBlob(blob, filename);
    } catch (error) {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: payerErrorMessage(t, error, t('payer.team.export.failed')),
        }),
      );
    } finally {
      setExporting(false);
    }
  };

  const policy = isOutsidePolicy(team.outside_policy)
    ? team.outside_policy
    : null;
  // The server decides who may change it: the Owner, or an Admin while the
  // team isn't locked.
  const canSetPolicy = team.can_set_outside_policy === true;

  const pickPolicy = (value: string) => {
    if (!isOutsidePolicy(value) || value === policy || !canSetPolicy) return;
    setPolicyPick(value);
    setOutside(null);
    teamsService
      .getOutside(team.id, token)
      .then((res) => setOutside(res))
      .catch(() => {
        // The confirm says what pauses without the numbers.
      });
  };

  const confirmPolicy = (next: OutsidePolicy) =>
    dispatch(
      setTeamOutsidePolicy({ teamId: team.id, policy: next, token }),
    ).unwrap();

  const confirmTransfer = async () => {
    if (!newOwnerRow) return;
    await teamsService.transferOwner(team.id, newOwnerRow.user_id, token);
    setNewOwnerRow(null);
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

  // Moving or deleting the team's items happens inside the team, and so
  // does removing its connections.
  const openTeam = (path: string = AGENTS_MANAGE_ROOT) => {
    navigate(path);
    if (workspaceId !== team.id) dispatch(switchWorkspace(team.id));
  };

  // Connections never move: they are removed, so they get their own line.
  const holdsConnections = !!notEmpty?.connection;
  const holdsItems =
    !!notEmpty &&
    Object.entries(notEmpty).some(
      ([kind, count]) => kind !== 'connection' && count > 0,
    );

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

      {policy && (
        <section className="border-border flex flex-col gap-4 border-t pt-6">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('settings.teams.outside.title')}
            description={t('settings.teams.outside.description')}
          />
          <RadioGroup
            value={policy}
            onValueChange={pickPolicy}
            aria-label={t('settings.teams.outside.label')}
            aria-describedby={
              canSetPolicy ? undefined : 'team-outside-policy-reason'
            }
          >
            {OUTSIDE_POLICIES.map((option) => {
              const id = `team-outside-policy-${option}`;
              return (
                <div key={option} className="flex items-start gap-3">
                  <RadioGroupItem
                    id={id}
                    value={option}
                    disabled={!canSetPolicy}
                    aria-describedby={`${id}-hint`}
                    className="mt-0.5"
                  />
                  <div className="flex min-w-0 flex-col gap-1">
                    <Label htmlFor={id}>
                      {t(`settings.teams.outside.policy.${option}`)}
                    </Label>
                    <p
                      id={`${id}-hint`}
                      className="text-muted-foreground text-sm"
                    >
                      {t(`settings.teams.outside.hint.${option}`)}
                    </p>
                  </div>
                </div>
              );
            })}
          </RadioGroup>
          {!canSetPolicy && (
            <p
              id="team-outside-policy-reason"
              className="text-muted-foreground text-sm"
            >
              {policy === 'locked'
                ? t('settings.teams.outside.ownerOnly')
                : t('settings.teams.errors.roleRequired')}
            </p>
          )}
        </section>
      )}

      {chatExport && (
        <section className="border-border flex flex-col gap-4 border-t pt-6">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('payer.team.export.title')}
            description={t('payer.team.export.description')}
          />
          <div>
            <Button
              variant="outline"
              size="field"
              shape="pill"
              onClick={handleExport}
              loading={exporting}
            >
              <FileDown aria-hidden />
              {t('payer.team.export.action')}
            </Button>
          </div>
        </section>
      )}

      {isOwner && (
        <section className="border-border flex flex-col gap-4 border-t pt-6">
          <SectionHeader
            as="h4"
            size="sm"
            title={t('settings.teams.transfer.title')}
            description={t('settings.teams.transfer.description')}
          />
          <div className="flex flex-wrap items-center gap-2">
            <Combobox
              options={candidates.map((m) => ({
                value: m.user_id,
                label: memberLabel(m),
              }))}
              value={newOwnerRow?.user_id ?? null}
              valueOption={
                newOwnerRow
                  ? {
                      value: newOwnerRow.user_id,
                      label: memberLabel(newOwnerRow),
                    }
                  : undefined
              }
              onValueChange={(id) =>
                setNewOwnerRow(candidates.find((m) => m.user_id === id) ?? null)
              }
              shouldFilter={false}
              search={memberQuery}
              onSearchChange={setMemberQuery}
              placeholder={t('settings.teams.transfer.placeholder')}
              searchPlaceholder={t('settings.teams.searchMembers')}
              emptyText={
                membersLoading
                  ? t('loading')
                  : t('settings.teams.transfer.noMatches')
              }
              aria-label={t('settings.teams.transfer.memberLabel')}
              disabled={!hasCandidates}
              className="w-full sm:w-72"
            />
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
                {holdsItems || !holdsConnections ? (
                  <p>
                    {t('settings.teams.notEmpty.hint')}{' '}
                    <AlertAction onClick={() => openTeam()}>
                      {t('settings.teams.notEmpty.open', {
                        interpolation: { escapeValue: false },
                        name: team.name,
                      })}
                    </AlertAction>
                  </p>
                ) : null}
                {holdsConnections ? (
                  <p>
                    {t('settings.teams.notEmpty.connectionsHint')}{' '}
                    <AlertAction onClick={() => openTeam(CONNECTORS_PATH)}>
                      {t('settings.teams.notEmpty.openConnectors')}
                    </AlertAction>
                  </p>
                ) : null}
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

      {policy && (
        <OutsidePolicyConfirm
          teamName={team.name}
          from={policy}
          to={policyPick}
          isOwner={isOwner}
          counts={
            outside
              ? {
                  shares: outside.shares?.length ?? 0,
                  published: outside.published?.length ?? 0,
                }
              : null
          }
          onClose={() => setPolicyPick(null)}
          onConfirm={confirmPolicy}
        />
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
