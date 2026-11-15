import {
  Bot,
  Cpu,
  Database,
  Folder as FolderIcon,
  type LucideIcon,
  MessageSquareText,
  Wrench,
} from 'lucide-react';
import { type ReactNode, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import type {
  MoveItemType,
  MovePlan,
  MoveRequest,
} from '../../api/services/workspacesService';
import {
  loadFolders,
  selectFolderTree,
} from '../../components/folders/foldersSlice';
import {
  buildFolderTree,
  folderPath,
  formatFolderPath,
  sortFoldersByName,
  subtreeHeight,
} from '../../components/folders/folderTree';
import { type Folder, MAX_FOLDER_DEPTH } from '../../components/folders/types';
import {
  Alert,
  AlertAction,
  AlertDescription,
} from '../../components/ui/alert';
import { FormField } from '../../components/ui/form-field';
import { ListRow, ListRows } from '../../components/ui/list-row';
import { LoadingState } from '../../components/ui/loading-state';
import { Modal, ModalActions } from '../../components/ui/modal';
import { SectionHeader } from '../../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { selectToken } from '../../preferences/preferenceSlice';
import type { AppDispatch } from '../../store';
import { cn } from '../../lib/utils';
import { readerIdFromToken } from '../../utils/personLabel';
import { PERSONAL_WORKSPACE } from '../requestWorkspace';
import useWorkspace from '../useWorkspace';
import { loadWorkspaces } from '../workspaceSlice';
import {
  borrowMessage,
  cannotMoveEffectKey,
  cannotMoveReasonKey,
  moveErrorMessage,
  moveKindKey,
  moveWithReasonKey,
  nameList,
  payerName,
} from './movePlanCopy';
import useMovePlan, { type MoveFailure } from './useMovePlan';
import {
  moveTargets,
  selectMoveCurrentId,
  selectMoveWorkspaces,
} from './moveTargets';

/** What the dialog moves: one item or folder, by type and id. */
export type MoveSubjectRef = {
  type: MoveItemType;
  id: string;
  /** Shown in the title. */
  name: string;
};

export type MoveToWorkspaceModalProps = {
  subject: MoveSubjectRef;
  /**
   * The workspace the item lives in: a team's item moves out to Personal,
   * a personal one into a team. The current workspace when left out.
   */
  from?: { kind: 'personal' | 'team'; team_id?: string | null } | null;
  /** The team a move in starts at (the share dialog's offer). */
  initialTeamId?: string;
  onClose: () => void;
  /** After the move went through, so the page can reload its list. */
  onMoved?: () => void;
};

// Radix Select can't hold an empty value: the top level gets a sentinel.
const NO_FOLDER = '__docsgpt-no-folder__';

const KIND_ICONS: Record<string, LucideIcon> = {
  agent: Bot,
  source: Database,
  tool: Wrench,
  prompt: MessageSquareText,
  folder: FolderIcon,
  model: Cpu,
};

const noEscape = { interpolation: { escapeValue: false } };

type TargetTree = { workspace: string; folders: Folder[]; failed: boolean };

/**
 * Move to team… / Move to Personal…: pick where it goes (a team where the
 * caller is Editor or above, or Personal for a team's item) and a folder
 * there, read what the move does, then confirm. The plan names who gains
 * and loses access, who owns it, who keeps paying, what comes along and
 * what can't; a move an agent with outside access would refuse stays
 * disabled with the reason on screen. Confirming sends the plan's
 * fingerprint: when the plan changed meanwhile the fresh one takes its place
 * with a notice. After the move the folder tree reloads, the page hears of
 * it, and the dialog offers to open the workspace it went to.
 */
export default function MoveToWorkspaceModal({
  subject,
  from,
  initialTeamId,
  onClose,
  onMoved,
}: MoveToWorkspaceModalProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const currentId = useSelector(selectMoveCurrentId) ?? PERSONAL_WORKSPACE;
  // A store without the workspace slice reads as Personal alone.
  const workspaces = useSelector(selectMoveWorkspaces) ?? [];
  const currentFolders = useSelector(selectFolderTree).items;
  const { switchTo } = useWorkspace();
  const me = useMemo(() => readerIdFromToken(token), [token]);

  const fromTeam = from
    ? from.kind === 'team'
      ? (from.team_id ?? currentId)
      : null
    : currentId !== PERSONAL_WORKSPACE
      ? currentId
      : null;
  const direction: 'in' | 'out' = fromTeam ? 'out' : 'in';
  const teams = useMemo(() => moveTargets(workspaces), [workspaces]);
  const [teamId, setTeamId] = useState<string | null>(
    () => initialTeamId ?? teams[0]?.id ?? null,
  );
  const target = direction === 'out' ? PERSONAL_WORKSPACE : teamId;
  const [folderId, setFolderId] = useState<string | null>(null);

  const [targetTree, setTargetTree] = useState<TargetTree | null>(null);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<MoveFailure | null>(null);
  const [done, setDone] = useState(false);

  // The target workspace's own tree, read with that workspace's header.
  useEffect(() => {
    if (!target) return;
    let live = true;
    userService
      .getFolders(token, { workspace: target })
      .then((response: Response) => {
        if (!response?.ok) throw new Error('folders');
        return response.json();
      })
      .then((data: { folders?: Folder[] }) => {
        if (!live) return;
        setTargetTree({
          workspace: target,
          folders: Array.isArray(data?.folders) ? data.folders : [],
          failed: false,
        });
      })
      .catch(() => {
        if (live)
          setTargetTree({ workspace: target, folders: [], failed: true });
      });
    return () => {
      live = false;
    };
  }, [target, token]);

  const request = useMemo<MoveRequest | null>(
    () =>
      target
        ? {
            to: { workspace: target, folder_id: folderId },
            items: [{ type: subject.type, id: subject.id }],
          }
        : null,
    [target, folderId, subject.type, subject.id],
  );
  const { plan, planning, planError, changed, retry, apply } = useMovePlan(
    request,
    token,
  );

  // The folders a move can land in; a moving folder can't push its deepest
  // subfolder past the depth limit.
  const folderOptions = useMemo(() => {
    const folders =
      targetTree && targetTree.workspace === target ? targetTree.folders : [];
    const tree = buildFolderTree(folders);
    const height =
      subject.type === 'folder'
        ? subtreeHeight(buildFolderTree(currentFolders), subject.id)
        : 0;
    return sortFoldersByName(folders)
      .map((folder) => {
        const path = folderPath(tree, folder.id);
        return {
          id: folder.id,
          label: formatFolderPath(path),
          tooDeep: path.length + height > MAX_FOLDER_DEPTH,
        };
      })
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [targetTree, target, currentFolders, subject.type, subject.id]);

  const sourceTeamName =
    workspaces.find((row) => row.id === fromTeam)?.name ?? '';
  const teamName =
    direction === 'in'
      ? plan?.to.workspace.name ||
        workspaces.find((row) => row.id === teamId)?.name ||
        ''
      : sourceTeamName;
  const targetName =
    direction === 'in' ? teamName : t('workspace.common.personal');

  const blocking = plan
    ? direction === 'out'
      ? plan.borrowing_agents
      : plan.borrowing_agents.filter((agent) => agent.published)
    : [];
  const hiddenBlocking = plan?.borrowing_others ?? 0;
  const keeps =
    plan && direction === 'in'
      ? plan.borrowing_agents.filter((agent) => !agent.published)
      : [];
  const needsAdmin = plan?.needs_admin ?? [];
  const blocked =
    blocking.length > 0 || hiddenBlocking > 0 || needsAdmin.length > 0;

  const submit = async () => {
    if (applying || !plan || blocked) return;
    setApplying(true);
    setApplyError(null);
    const result = await apply();
    setApplying(false);
    if (!result) return;
    if (result.ok) {
      setDone(true);
      void dispatch(loadFolders({ token }));
      onMoved?.();
      return;
    }
    // A fresh plan took the old one's place; its notice says so.
    if (result.error === 'move_plan_changed' && result.body?.plan) return;
    if (
      result.error === 'workspace_role_required' ||
      result.error === 'workspace_not_found'
    )
      void dispatch(loadWorkspaces({ token }));
    setApplyError({ error: result.error, body: result.body });
  };

  const errorText = (failure: MoveFailure) =>
    moveErrorMessage(t, { ...failure, direction, teamName });

  const named = (name: string | null | undefined) =>
    name || t('workspace.move.unnamed');
  const kindIcon = (type: string) => {
    const Icon = KIND_ICONS[type] ?? FolderIcon;
    return <Icon className="text-muted-foreground size-4" aria-hidden />;
  };

  const title = t(
    direction === 'in'
      ? 'workspace.move.titleToTeam'
      : 'workspace.move.titleToPersonal',
    { name: subject.name, ...noEscape },
  );

  if (done) {
    const openable = !!target && target !== currentId;
    return (
      <Modal
        open
        onOpenChange={(open) => !open && onClose()}
        size="lg"
        title={title}
        footer={
          <ModalActions
            cancelLabel={t('workspace.move.doneButton')}
            onCancel={onClose}
            submitLabel={
              openable
                ? t('workspace.move.openIn', { name: targetName, ...noEscape })
                : undefined
            }
            onSubmit={() => {
              onClose();
              if (target) switchTo(target);
            }}
          />
        }
      >
        <Alert variant="success">
          <AlertDescription>
            {t(
              direction === 'in'
                ? 'workspace.move.done.team'
                : 'workspace.move.done.personal',
              { name: subject.name, team: teamName, ...noEscape },
            )}
          </AlertDescription>
        </Alert>
      </Modal>
    );
  }

  const fields = (
    <div
      className={cn(
        'grid grid-cols-1 gap-x-4 gap-y-5',
        direction === 'in' && 'sm:grid-cols-2',
      )}
    >
      {direction === 'in' ? (
        <FormField label={t('workspace.move.teamLabel')}>
          <Select
            value={teamId ?? undefined}
            disabled={applying}
            onValueChange={(value) => {
              setTeamId(value);
              setFolderId(null);
              setApplyError(null);
            }}
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {teams.map((team) => (
                <SelectItem key={team.id} value={team.id}>
                  {team.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
      ) : null}
      <FormField
        label={t('workspace.move.folderLabel')}
        hint={
          targetTree?.failed ? t('workspace.move.foldersFailed') : undefined
        }
      >
        <Select
          value={folderId ?? NO_FOLDER}
          disabled={applying || !target}
          onValueChange={(value) => {
            setFolderId(value === NO_FOLDER ? null : value);
            setApplyError(null);
          }}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent capped>
            <SelectItem value={NO_FOLDER}>
              {t('workspace.move.noFolder')}
            </SelectItem>
            {folderOptions.map((option) => (
              <SelectItem
                key={option.id}
                value={option.id}
                disabled={option.tooDeep}
              >
                {option.tooDeep
                  ? `${option.label} · ${t('folders.tooDeep')}`
                  : option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
    </div>
  );

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open && !applying) onClose();
      }}
      isPerformingTask={applying}
      size="lg"
      title={title}
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={t('workspace.move.submit', {
            name: targetName,
            ...noEscape,
          })}
          onSubmit={submit}
          pending={applying}
          disabled={!plan || planning || blocked}
        />
      }
    >
      <div className="flex flex-col gap-6">
        {fields}
        {changed ? (
          <Alert variant="warning">
            <AlertDescription>
              {t('workspace.move.planChanged')}
            </AlertDescription>
          </Alert>
        ) : null}
        {applyError ? (
          <Alert variant="destructive">
            <AlertDescription>{errorText(applyError)}</AlertDescription>
          </Alert>
        ) : null}
        {planning ? (
          <LoadingState fill="block" size="sm" />
        ) : planError ? (
          <Alert variant="destructive">
            <AlertDescription>
              <p>
                {errorText(planError)}
                {planError.error === 'move_failed' ? (
                  <>
                    {' '}
                    <AlertAction onClick={retry}>{t('retry')}</AlertAction>
                  </>
                ) : null}
              </p>
            </AlertDescription>
          </Alert>
        ) : plan ? (
          <PlanBody
            plan={plan}
            direction={direction}
            teamName={teamName}
            me={me}
            blocking={blocking.map((agent) => named(agent.name))}
            hiddenBlocking={hiddenBlocking}
            keeps={keeps.map((agent) => named(agent.name))}
            named={named}
            kindIcon={kindIcon}
          />
        ) : null}
      </div>
    </Modal>
  );
}

type PlanBodyProps = {
  plan: MovePlan;
  direction: 'in' | 'out';
  teamName: string;
  me: string | undefined;
  blocking: string[];
  hiddenBlocking: number;
  keeps: string[];
  named: (name: string | null | undefined) => string;
  kindIcon: (type: string) => ReactNode;
};

/** Everything a plan says, blockers first so a disabled Move has its reason. */
function PlanBody({
  plan,
  direction,
  teamName,
  me,
  blocking,
  hiddenBlocking,
  keeps,
  named,
  kindIcon,
}: PlanBodyProps) {
  const { t } = useTranslation();
  const { access, kept } = plan;

  const accessTitle =
    direction === 'in'
      ? access.gains.total > 0
        ? t('workspace.move.access.gains', { count: access.gains.total })
        : t('workspace.move.access.gainsNone')
      : access.loses.length > 0
        ? t('workspace.move.access.loseTeam', {
            count: access.loses.length,
            team: teamName,
            ...noEscape,
          })
        : t('workspace.move.access.loseTeamNone');
  const accessDetail =
    direction === 'in'
      ? t('workspace.move.access.gainsDetail', { team: teamName, ...noEscape })
      : t('workspace.move.access.onlyYou');
  // Moving in, the people the item was shared with outside the team.
  const losesShared = direction === 'in' ? access.loses : [];

  const outside = kept.outside_access;
  const outsideParts = outside
    ? [
        outside.api_key && t('workspace.move.outside.apiKey'),
        outside.public_link && t('workspace.move.outside.publicLink'),
        outside.webhook && t('workspace.move.outside.webhook'),
      ].filter((part): part is string => !!part)
    : [];
  const schedulePayers = Array.from(
    new Set(kept.schedules.map((s) => payerName(t, s.paid_by, me))),
  );
  const pays = [
    t('workspace.move.pays.chats'),
    kept.schedules.length > 0
      ? t('workspace.move.pays.schedules', {
          count: kept.schedules.length,
          names: schedulePayers.join(t('workspace.move.listSeparator')),
          ...noEscape,
        })
      : null,
    outsideParts.length > 0
      ? t('workspace.move.pays.outside', {
          list: outsideParts.join(t('workspace.move.listSeparator')),
          name: payerName(t, outside?.paid_by, me),
          ...noEscape,
        })
      : null,
  ]
    .filter(Boolean)
    .join(' ');

  // What comes along, grouped by the item that brings it.
  const nameOf = new Map<string, string | null>();
  [...plan.items, ...plan.moves_with].forEach((item) =>
    nameOf.set(`${item.type}:${item.id}`, item.name),
  );
  const groups = new Map<string, MovePlan['moves_with']>();
  plan.moves_with.forEach((item) => {
    const key = `${item.via.type}:${item.via.id}`;
    groups.set(key, [...(groups.get(key) ?? []), item]);
  });

  const kind = (type: string) => t(moveKindKey(type));

  return (
    <>
      {plan.needs_admin.length > 0 ? (
        <Alert variant="warning">
          <AlertDescription>
            {t('workspace.move.needsAdmin', {
              count: plan.needs_admin.length,
              names: nameList(
                t,
                plan.needs_admin.map((agent) => named(agent.name)),
              ),
              team: teamName,
              ...noEscape,
            })}
          </AlertDescription>
        </Alert>
      ) : null}
      {blocking.length > 0 || hiddenBlocking > 0 ? (
        <Alert variant="warning">
          <AlertDescription>
            {borrowMessage(t, direction, blocking, hiddenBlocking, teamName)}
          </AlertDescription>
        </Alert>
      ) : null}
      {keeps.length > 0 ? (
        <Alert variant="info" role="note">
          <AlertDescription>
            {t('workspace.move.borrow.keeps', {
              count: keeps.length,
              names: nameList(t, keeps),
              ...noEscape,
            })}
          </AlertDescription>
        </Alert>
      ) : null}
      {losesShared.length > 0 ? (
        <Alert variant="warning">
          <AlertDescription>
            {t('workspace.move.access.losesShared', {
              count: losesShared.length,
              team: teamName,
              names: losesShared
                .map((person) => payerName(t, person, undefined))
                .join(t('workspace.move.listSeparator')),
              ...noEscape,
            })}
          </AlertDescription>
        </Alert>
      ) : null}

      <SectionHeader
        as="h3"
        size="xs"
        title={accessTitle}
        description={accessDetail}
      />
      <SectionHeader
        as="h3"
        size="xs"
        title={
          direction === 'in'
            ? t('workspace.move.owner.team', { team: teamName, ...noEscape })
            : t('workspace.move.owner.you')
        }
        description={
          direction === 'in'
            ? t('workspace.move.owner.teamDetail')
            : t('workspace.move.owner.youDetail', {
                team: teamName,
                ...noEscape,
              })
        }
      />
      <SectionHeader
        as="h3"
        size="xs"
        title={t('workspace.move.pays.title')}
        description={pays}
      />
      {plan.conversations_switched > 0 ? (
        <p className="text-muted-foreground text-sm">
          {t(`workspace.move.chats.${direction}`, {
            count: plan.conversations_switched,
            team: teamName,
            ...noEscape,
          })}
        </p>
      ) : null}

      {Array.from(groups.entries()).map(([key, rows]) => {
        const holder = nameOf.get(key);
        return (
          <section key={key} className="flex flex-col gap-1">
            <SectionHeader
              as="h3"
              size="xs"
              title={
                holder
                  ? t('workspace.move.comesWith', {
                      name: holder,
                      ...noEscape,
                    })
                  : t('workspace.move.comesAlong')
              }
              count={rows.length}
            />
            <ListRows>
              {rows.map((row) => (
                <ListRow
                  key={`${row.type}:${row.id}`}
                  leading={kindIcon(row.type)}
                  title={named(row.name)}
                  description={`${kind(row.type)} · ${t(moveWithReasonKey(row.reason))}`}
                />
              ))}
            </ListRows>
          </section>
        );
      })}

      {plan.cannot_move.length > 0 ? (
        <section className="flex flex-col gap-1">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('workspace.move.cannotTitle')}
            count={plan.cannot_move.length}
          />
          <ListRows>
            {plan.cannot_move.map((row) => (
              <ListRow
                key={`${row.type}:${row.id}`}
                wrap
                leading={<span className="mt-0.5">{kindIcon(row.type)}</span>}
                title={named(row.name)}
                description={`${kind(row.type)} · ${t(
                  cannotMoveReasonKey(row.reason),
                )} ${t(cannotMoveEffectKey(row.effect))}`}
              />
            ))}
          </ListRows>
        </section>
      ) : null}

      {plan.renames.length > 0 ? (
        <section className="flex flex-col gap-1">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('workspace.move.renames.title')}
          />
          <ListRows>
            {plan.renames.map((rename) => (
              <ListRow
                key={`${rename.type}:${rename.id}:${rename.field ?? ''}`}
                wrap
                leading={
                  <span className="mt-0.5">{kindIcon(rename.type)}</span>
                }
                title={t(
                  rename.field === 'slug'
                    ? 'workspace.move.renames.slug'
                    : rename.type === 'folder'
                      ? 'workspace.move.renames.folder'
                      : 'workspace.move.renames.other',
                  { from: rename.from, to: rename.to, ...noEscape },
                )}
              />
            ))}
          </ListRows>
        </section>
      ) : null}
    </>
  );
}
