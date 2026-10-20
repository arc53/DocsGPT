import { Pencil, Plus, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/empty-state';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';

import userService from '../../api/services/userService';
import { ActiveState } from '../../models/misc';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { showActionToast } from '../../notifications/actionToastSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import { analyticsOf, appendSuggestions, newTagId } from '../analyticsConfig';
import type {
  AnalyticsConfig,
  AnalyticsTag,
  AnalyticsTopic,
  AnalyticsTopicMode,
} from '../types';
import AnalyticsItemModal from './AnalyticsItemModal';

const DOCS_URL =
  'https://docs.docsgpt.cloud/Using/analytics-and-logs#analytics-settings-for-an-agent';

/** Fewer folders than this and the server asks no topic question. */
const MIN_AUTO_TOPICS = 2;

type Item = { name: string; description: string };

type Editing = {
  kind: 'topic' | 'tag';
  /** The row being edited; null to add one. */
  index: number | null;
  item?: Item;
};

/** The folders `auto` mode groups by, for one agent; `null` when they failed to load. */
type Folders = { agentId: string; topics: AnalyticsTopic[] | null };

export type InsightsSettingsBodyProps = {
  value?: AnalyticsConfig;
  onChange: (next: AnalyticsConfig) => void;
  /** A saved agent's id: the source folders need it. */
  agentId?: string;
  maxTopics: number;
  maxTags: number;
  /** The caller can't save the agent: the settings show, read-only. */
  disabled?: boolean;
  token: string | null;
  /**
   * Where `auto` topics come from. `sources` (a classic agent) shows its
   * source folders, with Customize and Reset to sources. `none` (a workflow,
   * which has no agent-level sources) offers only the owner's own list: on is
   * `custom`, off is `off`, and a stored `auto` reads as off.
   */
  topicSource?: 'sources' | 'none';
  /** The Topics and Tags heading level: `h4` inside a card that has its own `h3`. */
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

const sameTopics = (a: AnalyticsTopic[], b: AnalyticsTopic[]) =>
  a.length === b.length &&
  a.every(
    (topic, index) =>
      topic.name.trim() === b[index].name.trim() &&
      (topic.description ?? '').trim() === (b[index].description ?? '').trim(),
  );

async function loadFolders(
  agentId: string,
  token: string | null,
): Promise<AnalyticsTopic[]> {
  const response = await userService.getTopicSuggestions(agentId, token);
  if (!response.ok) throw new Error('topic suggestions');
  const body = (await response.json()) as {
    success?: boolean;
    topics?: AnalyticsTopic[];
  };
  if (!body?.success) throw new Error('topic suggestions');
  return body.topics ?? [];
}

/**
 * An agent's insights settings: Collect insights, how questions are grouped
 * into topics, the owner's yes/no tags and the weekly docs-gap summary. It
 * edits `value` only; the host saves it (the agent form's Save, a drawer's
 * or the workflow details' own). It renders its blocks as siblings, so the
 * host's flex column sets the gap between them. Everything but the first
 * switch hides while insights are off.
 */
export default function InsightsSettingsBody({
  value,
  onChange,
  agentId,
  maxTopics,
  maxTags,
  disabled = false,
  token,
  topicSource = 'sources',
  headingLevel = 'h3',
  active = true,
}: InsightsSettingsBodyProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const k = (key: string) => t(`agents.form.analytics.${key}`);

  const config = analyticsOf(value);
  const fromSources = topicSource === 'sources';
  const storedMode = config.topics.mode;
  // A workflow has no folders, so a stored `auto` asks no topic question.
  const mode: AnalyticsTopicMode =
    !fromSources && storedMode === 'auto' ? 'off' : storedMode;
  const topics = config.topics.items;
  const tags = config.tags;

  const [editing, setEditing] = React.useState<Editing | null>(null);
  const [removingTag, setRemovingTag] = React.useState<AnalyticsTag | null>(
    null,
  );
  const [confirmingReset, setConfirmingReset] = React.useState(false);
  const shownEditing = useKept(editing);
  const shownRemovingTag = useKept(removingTag);

  const [folders, setFolders] = React.useState<Folders | null>(null);
  const [customizing, setCustomizing] = React.useState(false);
  const folderTopics =
    agentId && folders?.agentId === agentId ? folders.topics : undefined;
  const wantsFolders =
    active &&
    fromSources &&
    !disabled &&
    !!agentId &&
    config.enabled &&
    mode !== 'off';
  const foldersLoaded = !!agentId && folders?.agentId === agentId;
  React.useEffect(() => {
    if (!wantsFolders || !agentId || foldersLoaded) return;
    let cancelled = false;
    loadFolders(agentId, token)
      .then((topics) => {
        if (!cancelled) setFolders({ agentId, topics });
      })
      .catch(() => {
        // A preview only: without it the switch's hint still says what it does.
        if (!cancelled) setFolders({ agentId, topics: null });
      });
    return () => {
      cancelled = true;
    };
  }, [wantsFolders, agentId, token, foldersLoaded]);

  const enabledId = React.useId();
  const groupId = React.useId();
  const digestId = React.useId();

  const patch = (next: Partial<AnalyticsConfig>) =>
    onChange({ ...config, ...next });
  const setTopics = (topicsNext: Partial<AnalyticsConfig['topics']>) =>
    patch({ topics: { ...config.topics, ...topicsNext } });
  const setTags = (next: AnalyticsTag[]) => patch({ tags: next });

  /** The folders as a custom list: no reserved name, no repeats, within the limit. */
  const asList = (source: AnalyticsTopic[]) =>
    appendSuggestions([], source, maxTopics);

  const customize = async () => {
    let source = folderTopics ?? null;
    if (agentId && !source) {
      setCustomizing(true);
      try {
        source = await loadFolders(agentId, token);
        setFolders({ agentId, topics: source });
      } catch {
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: k('suggestFailed'),
          }),
        );
        return;
      } finally {
        setCustomizing(false);
      }
    }
    setTopics({ mode: 'custom', items: asList(source ?? []) });
  };

  const resetToSources = () => setTopics({ mode: 'auto', items: [] });
  const askResetToSources = () => {
    // Back to the folders drops the edits, so a list that differs confirms.
    const unchanged =
      topics.length === 0 ||
      (Array.isArray(folderTopics) && sameTopics(topics, asList(folderTopics)));
    if (unchanged) resetToSources();
    else setConfirmingReset(true);
  };

  const setGrouping = (on: boolean) => {
    if (!on) setTopics({ mode: 'off' });
    // A list of its own comes back; otherwise the folders (a workflow has none).
    else
      setTopics({
        mode: !fromSources || topics.length > 0 ? 'custom' : 'auto',
      });
  };

  const saveItem = (item: Item) => {
    if (!editing) return;
    if (editing.kind === 'topic') {
      setTopics({
        items:
          editing.index === null
            ? [...topics, item]
            : topics.map((topic, index) =>
                index === editing.index ? item : topic,
              ),
      });
    } else {
      setTags(
        editing.index === null
          ? [...tags, { id: newTagId(), ...item }]
          : // An edit keeps the id, so a renamed tag keeps its history.
            tags.map((tag, index) =>
              index === editing.index ? { ...tag, ...item } : tag,
            ),
      );
    }
    setEditing(null);
  };

  const others = shownEditing
    ? (shownEditing.kind === 'topic' ? topics : tags)
        .filter((_, index) => index !== shownEditing.index)
        .map((item) => item.name)
    : [];

  // DESIGN › Counts: a plain number, and the limit only once it is reached.
  const countOf = (count: number, max: number) =>
    count >= max
      ? t('agents.form.analytics.countOf', {
          count: formatCount(count),
          max: formatCount(max),
        })
      : count;

  const itemMenu = (name: string, onEdit: () => void, onRemove: () => void) =>
    disabled ? undefined : (
      <ActionMenu
        triggerLabel={t('agents.form.analytics.itemActions', {
          name,
          interpolation: { escapeValue: false },
        })}
        options={[
          { label: k('edit'), icon: Pencil, onClick: onEdit },
          {
            label: k('remove'),
            icon: Trash2,
            onClick: onRemove,
            variant: 'destructive',
            separatorBefore: true,
          },
        ]}
      />
    );

  const addButton = (label: string, onClick: () => void) => (
    <Button type="button" variant="outline" size="sm" onClick={onClick}>
      <Plus />
      {label}
    </Button>
  );

  const ownList = mode === 'custom';
  const topicActions = disabled ? undefined : mode === 'auto' ? (
    <Button
      type="button"
      variant="outline"
      size="sm"
      loading={customizing}
      onClick={customize}
    >
      {k('customize')}
    </Button>
  ) : ownList ? (
    <>
      {fromSources && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={askResetToSources}
        >
          {k('resetToSources')}
        </Button>
      )}
      {topics.length < maxTopics &&
        addButton(k('addTopic'), () =>
          setEditing({ kind: 'topic', index: null }),
        )}
    </>
  ) : undefined;

  const topicHint =
    mode === 'off' ? (fromSources ? 'off' : 'workflowOff') : mode;

  const folderList =
    mode !== 'auto' || !folderTopics ? null : folderTopics.length <
      MIN_AUTO_TOPICS ? (
      <EmptyState size="sm" illustration="none" title={k('autoTopicsNone')} />
    ) : (
      <Card variant="subtle" padding="none" className="overflow-hidden">
        <ListRows>
          {folderTopics.map((topic) => (
            <ListRow
              key={topic.name}
              title={topic.name}
              description={topic.description || undefined}
            />
          ))}
        </ListRows>
      </Card>
    );

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
              count={
                ownList && topics.length > 0
                  ? countOf(topics.length, maxTopics)
                  : undefined
              }
              description={k('topicsDescription')}
              actions={topicActions}
            />
            <SettingRow
              label={k('groupByTopic')}
              description={k(`topicHints.${topicHint}`)}
              htmlFor={groupId}
              alignStart
            >
              <Switch
                id={groupId}
                checked={mode !== 'off'}
                disabled={disabled}
                data-testid="analytics-group-topics"
                onCheckedChange={setGrouping}
              />
            </SettingRow>
            {folderList}
            {ownList && (
              <Card variant="subtle" padding="none" className="overflow-hidden">
                {topics.length > 0 ? (
                  <ListRows>
                    {topics.map((topic, index) => (
                      <ListRow
                        key={topic.name}
                        title={topic.name}
                        description={topic.description || undefined}
                        trailing={itemMenu(
                          topic.name,
                          () =>
                            setEditing({ kind: 'topic', index, item: topic }),
                          // Topic history is keyed by name: adding it back
                          // restores it, so no confirm.
                          () =>
                            setTopics({
                              items: topics.filter((_, i) => i !== index),
                            }),
                        )}
                      />
                    ))}
                  </ListRows>
                ) : (
                  <EmptyState
                    size="sm"
                    illustration="none"
                    title={k('topicsEmpty')}
                  />
                )}
              </Card>
            )}
          </div>

          {maxTags > 0 && (
            <div className="flex flex-col gap-3" data-testid="analytics-tags">
              <SectionHeader
                as={headingLevel}
                size="xs"
                title={k('tags')}
                count={
                  tags.length > 0 ? countOf(tags.length, maxTags) : undefined
                }
                description={k('tagsDescription')}
                actions={
                  !disabled && tags.length < maxTags
                    ? addButton(k('addTag'), () =>
                        setEditing({ kind: 'tag', index: null }),
                      )
                    : undefined
                }
              />
              <Card variant="subtle" padding="none" className="overflow-hidden">
                {tags.length > 0 ? (
                  <ListRows>
                    {tags.map((tag, index) => (
                      <ListRow
                        key={tag.id}
                        title={tag.name}
                        description={tag.description}
                        trailing={itemMenu(
                          tag.name,
                          () => setEditing({ kind: 'tag', index, item: tag }),
                          () => setRemovingTag(tag),
                        )}
                      />
                    ))}
                  </ListRows>
                ) : (
                  <EmptyState
                    size="sm"
                    illustration="none"
                    title={k('tagsEmpty')}
                  />
                )}
              </Card>
            </div>
          )}

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

      <AnalyticsItemModal
        kind={shownEditing?.kind ?? 'tag'}
        item={shownEditing?.item}
        others={others}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSubmit={saveItem}
      />
      <ConfirmationModal
        message={t('agents.form.analytics.removeTag.title', {
          name: shownRemovingTag?.name ?? '',
          interpolation: { escapeValue: false },
        })}
        description={k('removeTag.description')}
        modalState={removingTag ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state: ActiveState) => {
          if (state === 'INACTIVE') setRemovingTag(null);
        }}
        submitLabel={k('removeTag.submit')}
        handleSubmit={() => {
          if (removingTag)
            setTags(tags.filter((tag) => tag.id !== removingTag.id));
          setRemovingTag(null);
        }}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
      <ConfirmationModal
        message={k('resetTopics.title')}
        description={k('resetTopics.description')}
        modalState={confirmingReset ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state: ActiveState) => {
          if (state === 'INACTIVE') setConfirmingReset(false);
        }}
        submitLabel={k('resetTopics.submit')}
        handleSubmit={() => {
          resetToSources();
          setConfirmingReset(false);
        }}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
    </>
  );
}
