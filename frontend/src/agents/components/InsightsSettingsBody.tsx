import { EyeOff, Folder, Pencil, Plus, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/empty-state';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow } from '@/components/ui/setting-row';
import { Skeleton } from '@/components/ui/skeleton';
import { Switch } from '@/components/ui/switch';

import userService from '../../api/services/userService';
import { ActiveState } from '../../models/misc';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  analyticsOf,
  byName,
  newTopicId,
  topicsOfKind,
  visibleFolders,
} from '../analyticsConfig';
import type { AnalyticsConfig, AnalyticsTopic, TopicFolder } from '../types';
import TopicModal, { type TopicDraft } from './TopicModal';

const DOCS_URL =
  'https://docs.docsgpt.cloud/Using/analytics-and-logs#analytics-settings-for-an-agent';

type Editing = {
  /** The owner's topic being edited, by index; null to add one. */
  index: number | null;
  item?: AnalyticsTopic;
  /** The folder being edited: saving hides it and adds an own topic. */
  folder?: TopicFolder;
};

/** One agent's source folders, largest first; `null` when they failed to load. */
type Folders = { agentId: string; folders: TopicFolder[] | null };

/** A row of the list: one of the owner's topics, or a source folder. */
type Row =
  | { kind: 'own'; topic: AnalyticsTopic; index: number }
  | { kind: 'folder'; folder: TopicFolder };

export type InsightsSettingsBodyProps = {
  value?: AnalyticsConfig;
  onChange: (next: AnalyticsConfig) => void;
  /** A saved agent's id: the source folders need it. */
  agentId?: string;
  maxTopics: number;
  maxOverlapping: number;
  /** The caller can't save the agent: the settings show, read-only. */
  disabled?: boolean;
  token: string | null;
  /**
   * Whether the agent has source folders. `none` (a workflow, which has no
   * agent-level sources) offers only the owner's own topics.
   */
  topicSource?: 'sources' | 'none';
  /** The Topics heading level: `h4` inside a card that has its own `h3`. */
  headingLevel?: 'h3' | 'h4';
  /**
   * The body is on screen (its section is open, its drawer shown). The
   * source folders load only then, once per agent.
   */
  active?: boolean;
};

/**
 * The last non-null `value`, so a dialog keeps its copy while it animates
 * closed after its subject is cleared.
 */
function useKept<T>(value: T | null): T | null {
  const [kept, setKept] = React.useState(value);
  if (value !== null && value !== kept) setKept(value);
  return value ?? kept;
}

async function loadFolders(
  agentId: string,
  token: string | null,
): Promise<TopicFolder[]> {
  const response = await userService.getTopicFolders(agentId, token);
  if (!response.ok) throw new Error('topic folders');
  const body = (await response.json()) as {
    success?: boolean;
    folders?: TopicFolder[];
  };
  if (!body?.success) throw new Error('topic folders');
  return body.folders ?? [];
}

const nextHeading = (level: 'h3' | 'h4') => (level === 'h3' ? 'h4' : 'h5');

/**
 * An agent's insights settings: Collect insights, its topics and the weekly
 * docs-gap summary. The topics are one list: the agent's source folders,
 * then the owner's own, each either sorting questions (one per question) or
 * able to overlap (checked on whole conversations). The list splits into
 * those two groups only once a topic overlaps. It edits `value` only; the
 * host saves it (the agent form's Save, a drawer's or the workflow details'
 * own). It renders its blocks as siblings, so the host's flex column sets
 * the gap between them. Everything but the first switch hides while
 * insights are off.
 */
export default function InsightsSettingsBody({
  value,
  onChange,
  agentId,
  maxTopics,
  maxOverlapping,
  disabled = false,
  token,
  topicSource = 'sources',
  headingLevel = 'h3',
  active = true,
}: InsightsSettingsBodyProps) {
  const { t } = useTranslation();
  const k = (key: string) => t(`agents.form.analytics.${key}`);

  const config = analyticsOf(value);
  const fromSources = topicSource === 'sources';
  const own = config.topics;
  const onePickOwn = topicsOfKind(config, false);
  const overlapping = topicsOfKind(config, true);

  const [editing, setEditing] = React.useState<Editing | null>(null);
  const [removing, setRemoving] = React.useState<AnalyticsTopic | null>(null);
  const shownEditing = useKept(editing);
  const shownRemoving = useKept(removing);

  const [folders, setFolders] = React.useState<Folders | null>(null);
  const [attempt, setAttempt] = React.useState(0);
  const loaded = agentId && folders?.agentId === agentId ? folders : null;
  // A read-only caller can't list them (the endpoint needs edit access), and
  // a save in flight keeps what was loaded.
  const wantsFolders =
    active && fromSources && !disabled && !!agentId && config.enabled;
  React.useEffect(() => {
    if (!wantsFolders || !agentId || loaded) return;
    let cancelled = false;
    loadFolders(agentId, token)
      .then((list) => {
        if (!cancelled) setFolders({ agentId, folders: list });
      })
      .catch(() => {
        if (!cancelled) setFolders({ agentId, folders: null });
      });
    return () => {
      cancelled = true;
    };
  }, [wantsFolders, agentId, token, loaded, attempt]);

  const enabledId = React.useId();
  const digestId = React.useId();

  const patch = (next: Partial<AnalyticsConfig>) =>
    onChange({ ...config, ...next });

  const folderList = loaded?.folders ?? [];
  const view = visibleFolders(folderList, config, maxTopics);
  const foldersFailed = loaded !== null && loaded.folders === null;
  const foldersLoading =
    fromSources && !!agentId && wantsFolders && loaded === null;
  // Folders come once the agent is saved; a read-only caller can't list them.
  const unsaved = fromSources && !agentId;
  const unlisted = fromSources && !!agentId && disabled && !loaded;

  const onePickRows: Row[] = byName([
    ...view.shown.map((folder) => ({ name: folder.name, folder })),
    ...onePickOwn.map((topic) => ({ name: topic.name, topic })),
  ]).map((entry) =>
    'folder' in entry
      ? { kind: 'folder', folder: entry.folder }
      : { kind: 'own', topic: entry.topic, index: own.indexOf(entry.topic) },
  );
  const overlapRows: Row[] = byName(overlapping).map((topic) => ({
    kind: 'own',
    topic,
    index: own.indexOf(topic),
  }));
  const total = onePickRows.length + overlapRows.length;

  const onePickFull = onePickOwn.length >= maxTopics;
  const overlapFull = overlapping.length >= maxOverlapping;
  const canAdd = !disabled && !(onePickFull && overlapFull);

  const hide = (folder: TopicFolder) =>
    patch({ hidden_folders: [...config.hidden_folders, folder.name] });
  const showHidden = () => patch({ hidden_folders: [] });
  const removeTopic = (topic: AnalyticsTopic) =>
    patch({ topics: own.filter((item) => item.id !== topic.id) });

  const saveTopic = (draft: TopicDraft) => {
    if (!editing) return;
    if (editing.index !== null) {
      // An edit keeps the id, so a renamed overlapping topic keeps its history.
      patch({
        topics: own.map((topic, index) =>
          index === editing.index ? { ...topic, ...draft } : topic,
        ),
      });
    } else {
      patch({
        topics: [...own, { id: newTopicId(), ...draft }],
        // An edited folder becomes the owner's own topic; the folder hides.
        ...(editing.folder
          ? {
              hidden_folders: [...config.hidden_folders, editing.folder.name],
            }
          : {}),
      });
    }
    setEditing(null);
  };

  // The dialog's limits leave out the topic being edited, so it may keep its kind.
  const editedOverlap = shownEditing?.item?.overlap;
  const others = shownEditing
    ? [
        ...own
          .filter((_, index) => index !== shownEditing.index)
          .map((topic) => topic.name),
        ...view.shown
          .filter((folder) => folder !== shownEditing.folder)
          .map((folder) => folder.name),
      ]
    : [];

  const menu = (
    name: string,
    options: Parameters<typeof ActionMenu>[0]['options'],
  ) =>
    disabled ? undefined : (
      <ActionMenu
        triggerLabel={t('agents.form.analytics.itemActions', {
          name,
          interpolation: { escapeValue: false },
        })}
        options={options}
      />
    );

  const renderRow = (row: Row) =>
    row.kind === 'folder' ? (
      <ListRow
        key={`folder:${row.folder.name}`}
        title={
          <span className="flex min-w-0 items-center gap-2">
            <span className="truncate">{row.folder.name}</span>
            <Badge variant="neutral">
              <Folder />
              {k('fromSources')}
            </Badge>
          </span>
        }
        description={row.folder.description || undefined}
        trailing={menu(row.folder.name, [
          {
            label: k('edit'),
            icon: Pencil,
            onClick: () => setEditing({ index: null, folder: row.folder }),
          },
          { label: k('hide'), icon: EyeOff, onClick: () => hide(row.folder) },
        ])}
      />
    ) : (
      <ListRow
        key={row.topic.id}
        title={row.topic.name}
        description={row.topic.description || undefined}
        trailing={menu(row.topic.name, [
          {
            label: k('edit'),
            icon: Pencil,
            onClick: () => setEditing({ index: row.index, item: row.topic }),
          },
          {
            label: k('remove'),
            icon: Trash2,
            // An overlapping topic has results of its own, which go with it;
            // one that doesn't is keyed by name, so adding it back restores it.
            onClick: () =>
              row.topic.overlap
                ? setRemoving(row.topic)
                : removeTopic(row.topic),
            variant: 'destructive',
            separatorBefore: true,
          },
        ])}
      />
    );

  const groupLabel = (title: string, description?: string) => (
    <div className="px-4 pt-3 pb-1">
      <SectionHeader
        as={nextHeading(headingLevel)}
        size="sm"
        title={title}
        description={description}
      />
    </div>
  );

  // Footer lines, in the card under the rows.
  const notes: React.ReactNode[] = [];
  const note = (key: string, text: React.ReactNode, action?: React.ReactNode) =>
    notes.push(
      <div
        key={key}
        className="text-muted-foreground flex items-center justify-between gap-3 px-4 py-2.5 text-xs"
      >
        <span>{text}</span>
        {action}
      </div>,
    );
  const link = (label: string, onClick: () => void) => (
    <Button
      type="button"
      variant="link"
      size="text"
      // size="text" inherits the note's text-xs.
      className="shrink-0"
      onClick={onClick}
    >
      {label}
    </Button>
  );
  const names = (list: TopicFolder[]) =>
    list.map((folder) => folder.name).join(', ');
  if (foldersFailed)
    note(
      'failed',
      k('notes.foldersFailed'),
      link(t('retry'), () => {
        setFolders(null);
        setAttempt((n) => n + 1);
      }),
    );
  if (unsaved && total > 0) note('unsaved', k('notes.unsaved'));
  if (unlisted) note('unlisted', k('notes.unlisted'));
  if (view.hidden.length > 0)
    note(
      'hidden',
      t('agents.form.analytics.notes.hidden', {
        names: names(view.hidden),
        interpolation: { escapeValue: false },
      }),
      disabled ? undefined : link(k('notes.show'), showHidden),
    );
  if (view.cut.length > 0)
    note(
      'cut',
      t('agents.form.analytics.notes.cut', {
        names: names(view.cut),
        interpolation: { escapeValue: false },
      }),
    );
  // One topic on its own is a choice that says nothing; the server asks none.
  if (onePickRows.length === 1 && !unsaved && !unlisted)
    note('single', k('notes.single'));
  if (!disabled && onePickFull && overlapFull)
    note(
      'full',
      t('agents.form.analytics.notes.full', {
        topics: formatCount(maxTopics),
        overlapping: formatCount(maxOverlapping),
      }),
    );

  const emptyDescription = !fromSources
    ? k('empty.workflow')
    : unsaved
      ? k('empty.unsaved')
      : view.hidden.length > 0
        ? k('empty.allHidden')
        : k('empty.noFolders');

  let list: React.ReactNode;
  if (foldersLoading && own.length === 0) {
    list = (
      <ul aria-busy="true" className="divide-border divide-y">
        {[0, 1, 2].map((n) => (
          <li key={n} className="flex flex-col gap-2 px-4 py-3">
            <Skeleton className="h-4 w-28" />
            <Skeleton className="h-3 w-56" />
          </li>
        ))}
      </ul>
    );
  } else if (total === 0 && !foldersFailed && !unlisted) {
    list = (
      <EmptyState
        size="sm"
        illustration="none"
        title={k('empty.title')}
        description={emptyDescription}
        action={
          !disabled && view.hidden.length > 0 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={showHidden}
            >
              {k('empty.showFolders')}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (overlapRows.length > 0) {
    list = (
      <>
        {onePickRows.length > 0 && (
          <div>
            {groupLabel(k('groups.onePick'))}
            <ListRows>{onePickRows.map(renderRow)}</ListRows>
          </div>
        )}
        <div className={onePickRows.length > 0 ? 'border-t' : undefined}>
          {groupLabel(k('groups.overlap'), k('groups.overlapDescription'))}
          <ListRows>{overlapRows.map(renderRow)}</ListRows>
        </div>
      </>
    );
  } else {
    list = <ListRows>{onePickRows.map(renderRow)}</ListRows>;
  }

  return (
    <>
      <SettingRow
        label={k('enable')}
        description={
          <>
            {k('enableDescription')}{' '}
            <Button variant="link" size="text" asChild>
              <a href={DOCS_URL} target="_blank" rel="noopener noreferrer">
                {k('learnMore')}
              </a>
            </Button>
          </>
        }
        htmlFor={enabledId}
        alignStart
      >
        <Switch
          id={enabledId}
          checked={config.enabled}
          disabled={disabled}
          data-testid="analytics-enabled"
          onCheckedChange={(checked) => patch({ enabled: checked })}
        />
      </SettingRow>

      {config.enabled && (
        <>
          <div className="flex flex-col gap-3" data-testid="analytics-topics">
            <SectionHeader
              as={headingLevel}
              size="xs"
              title={k('topics')}
              count={total > 0 ? total : undefined}
              description={k('topicsDescription')}
              actions={
                canAdd ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setEditing({ index: null })}
                  >
                    <Plus />
                    {k('addTopic')}
                  </Button>
                ) : undefined
              }
            />
            <Card
              variant="subtle"
              padding="none"
              className="gap-0 overflow-hidden"
            >
              {list}
              {notes.length > 0 && (
                <div
                  className={
                    total > 0 || foldersLoading
                      ? 'divide-y border-t'
                      : 'divide-y'
                  }
                >
                  {notes}
                </div>
              )}
            </Card>
          </div>

          <SettingRow
            label={k('digest')}
            description={k('digestDescription')}
            htmlFor={digestId}
            alignStart
          >
            <Switch
              id={digestId}
              checked={config.digest}
              disabled={disabled}
              data-testid="analytics-digest"
              onCheckedChange={(checked) => patch({ digest: checked })}
            />
          </SettingRow>
        </>
      )}

      <TopicModal
        item={shownEditing?.item}
        folder={shownEditing?.folder}
        others={others}
        overlapAllowed={maxOverlapping > 0}
        onePickFull={
          onePickOwn.length - (editedOverlap === false ? 1 : 0) >= maxTopics
        }
        overlapFull={
          overlapping.length - (editedOverlap === true ? 1 : 0) >=
          maxOverlapping
        }
        maxTopics={maxTopics}
        maxOverlapping={maxOverlapping}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSubmit={saveTopic}
      />
      <ConfirmationModal
        message={t('agents.form.analytics.removeTopic.title', {
          name: shownRemoving?.name ?? '',
          interpolation: { escapeValue: false },
        })}
        description={k('removeTopic.description')}
        modalState={removing ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state: ActiveState) => {
          if (state === 'INACTIVE') setRemoving(null);
        }}
        submitLabel={k('removeTopic.submit')}
        handleSubmit={() => {
          if (removing) removeTopic(removing);
          setRemoving(null);
        }}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
    </>
  );
}
