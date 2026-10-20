import { Plus } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import ViewOnlyNotice from '@/components/ViewOnlyNotice';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ActionMenu } from '@/components/ui/dropdown-menu';
import { EmptyState } from '@/components/ui/empty-state';
import { FormField } from '@/components/ui/form-field';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

import userService from '../../api/services/userService';
import { ActiveState } from '../../models/misc';
import ConfirmationModal from '../../modals/ConfirmationModal';
import { showActionToast } from '../../notifications/actionToastSlice';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  analyticsOf,
  appendSuggestions,
  isDefaultAnalytics,
  newTagId,
} from '../analyticsConfig';
import type {
  AnalyticsConfig,
  AnalyticsTag,
  AnalyticsTopic,
  AnalyticsTopicMode,
} from '../types';
import AnalyticsItemModal from './AnalyticsItemModal';

const DOCS_URL =
  'https://docs.docsgpt.cloud/Using/analytics-and-logs#analytics-settings-for-an-agent';

const TOPIC_MODES: AnalyticsTopicMode[] = ['auto', 'custom', 'off'];

/** Fewer folders than this and the server asks no topic question. */
const MIN_AUTO_TOPICS = 2;

type SuggestNote = 'none' | 'noNew' | 'full';

const SUGGEST_NOTE_KEYS: Record<SuggestNote, string> = {
  none: 'agents.form.analytics.suggestNone',
  noNew: 'agents.form.analytics.suggestNoNew',
  full: 'agents.form.analytics.suggestFull',
};

type Editing =
  | { kind: 'topic'; index: number | null }
  | { kind: 'tag'; index: number | null }
  | null;

type AnalyticsSectionProps = {
  value?: AnalyticsConfig;
  onChange: (next: AnalyticsConfig) => void;
  /** A saved agent's id: topic suggestions need it. */
  agentId?: string;
  /** The server lets the decision model label conversations. */
  available: boolean;
  maxTopics: number;
  maxTags: number;
  /** The caller can't save the agent: the settings show, read-only. */
  disabled?: boolean;
  token: string | null;
};

/**
 * The agent form's Analytics panel: whether the agent's conversations are
 * labelled, how questions are grouped by topic, the owner's yes/no tags and
 * the weekly docs-gap notification. Not policy, so anyone who can save the
 * agent changes it. Hidden while the server has labelling off, unless the
 * agent already has settings of its own to see and change.
 */
export default function AnalyticsSection({
  value,
  onChange,
  agentId,
  available,
  maxTopics,
  maxTags,
  disabled = false,
  token,
}: AnalyticsSectionProps) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const [expanded, setExpanded] = React.useState(false);
  const [editing, setEditing] = React.useState<Editing>(null);
  const [removingTag, setRemovingTag] = React.useState<AnalyticsTag | null>(
    null,
  );
  const [suggesting, setSuggesting] = React.useState(false);
  const [suggestNote, setSuggestNote] = React.useState<SuggestNote | null>(
    null,
  );
  // What "From sources" groups by, for a saved agent: the same rule the
  // server applies.
  const [autoTopics, setAutoTopics] = React.useState<AnalyticsTopic[] | null>(
    null,
  );
  const autoMode =
    available &&
    analyticsOf(value).enabled &&
    analyticsOf(value).topics.mode === 'auto';
  React.useEffect(() => {
    if (!autoMode || !agentId) {
      setAutoTopics(null);
      return;
    }
    let cancelled = false;
    userService
      .getTopicSuggestions(agentId, token)
      .then((response) => {
        if (!response.ok) throw new Error('topic suggestions');
        return response.json();
      })
      .then((body: { success?: boolean; topics?: AnalyticsTopic[] }) => {
        if (!cancelled)
          setAutoTopics(body?.success ? (body.topics ?? []) : null);
      })
      .catch(() => {
        // A preview only: without it the mode's hint still says what it does.
        if (!cancelled) setAutoTopics(null);
      });
    return () => {
      cancelled = true;
    };
  }, [autoMode, agentId, token]);
  const bodyId = React.useId();
  const enabledId = React.useId();
  const digestId = React.useId();

  const config = analyticsOf(value);
  if (!available && isDefaultAnalytics(value)) return null;

  const patch = (next: Partial<AnalyticsConfig>) =>
    onChange({ ...config, ...next });
  const setTopics = (items: AnalyticsTopic[]) => {
    setSuggestNote(null);
    patch({ topics: { ...config.topics, items } });
  };
  const setTags = (tags: AnalyticsTag[]) => patch({ tags });

  const topics = config.topics.items;
  const tags = config.tags;
  const mode = config.topics.mode;

  const suggest = async () => {
    if (!agentId) return;
    setSuggesting(true);
    setSuggestNote(null);
    try {
      const response = await userService.getTopicSuggestions(agentId, token);
      if (!response.ok) throw new Error('topic suggestions');
      const body = await response.json();
      if (!body?.success) throw new Error('topic suggestions');
      const result = appendSuggestions(topics, body.topics ?? [], maxTopics);
      if (result.items !== topics)
        patch({ topics: { ...config.topics, items: result.items } });
      setSuggestNote(result.note);
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('agents.form.analytics.suggestFailed'),
        }),
      );
    } finally {
      setSuggesting(false);
    }
  };

  const editingItem =
    editing && editing.index !== null
      ? (editing.kind === 'topic' ? topics : tags)[editing.index]
      : undefined;
  const others = editing
    ? (editing.kind === 'topic' ? topics : tags)
        .filter((_, index) => index !== editing.index)
        .map((item) => item.name)
    : [];

  const saveItem = (item: { name: string; description: string }) => {
    if (!editing) return;
    if (editing.kind === 'topic') {
      setTopics(
        editing.index === null
          ? [...topics, item]
          : topics.map((topic, index) =>
              index === editing.index ? item : topic,
            ),
      );
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

  const countOf = (count: number, max: number) =>
    t('agents.form.analytics.countOf', {
      count: formatCount(count),
      max: formatCount(max),
    });

  const itemMenu = (name: string, onEdit: () => void, onRemove: () => void) =>
    disabled ? undefined : (
      <ActionMenu
        triggerLabel={t('agents.form.analytics.itemActions', {
          name,
          interpolation: { escapeValue: false },
        })}
        options={[
          { label: t('agents.form.analytics.edit'), onClick: onEdit },
          {
            label: t('agents.form.analytics.remove'),
            onClick: onRemove,
            variant: 'destructive',
            separatorBefore: true,
          },
        ]}
      />
    );

  return (
    <Card
      variant="subtle"
      padding="lg"
      className="gap-5"
      data-testid="analytics-section"
    >
      <div>
        <h2>
          <CollapsibleTrigger
            look="section"
            open={expanded}
            onOpenChange={setExpanded}
            controls={bodyId}
            data-testid="analytics-toggle"
          >
            {t('agents.form.sections.analytics')}
          </CollapsibleTrigger>
        </h2>

        <Collapsible open={expanded} id={bodyId}>
          <div className="flex flex-col gap-5 pt-5">
            {disabled && <ViewOnlyNotice />}
            {!available && (
              <Alert variant="info" role="note">
                <AlertDescription>
                  {t('agents.form.analytics.serverOff')}
                </AlertDescription>
              </Alert>
            )}

            <SettingRow
              label={t('agents.form.analytics.enable')}
              description={
                <>
                  {t('agents.form.analytics.enableDescription')}{' '}
                  <Button variant="link" size="text" asChild>
                    <a
                      href={DOCS_URL}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {t('agents.form.analytics.learnMore')}
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
                <div className="flex flex-col gap-2">
                  <FormField
                    float={false}
                    label={t('agents.form.analytics.topics')}
                    hint={t(`agents.form.analytics.topicHints.${mode}`)}
                    disabled={disabled}
                  >
                    <ToggleGroup
                      type="single"
                      fill
                      value={mode}
                      disabled={disabled}
                      aria-label={t('agents.form.analytics.topics')}
                      data-testid="analytics-topic-mode"
                      onValueChange={(next) => {
                        if (!next) return;
                        setSuggestNote(null);
                        // The custom list is kept while another mode is on, so
                        // it comes back when Custom is picked again.
                        patch({
                          topics: {
                            ...config.topics,
                            mode: next as AnalyticsTopicMode,
                          },
                        });
                      }}
                    >
                      {TOPIC_MODES.map((topicMode) => (
                        <ToggleGroupItem key={topicMode} value={topicMode}>
                          {t(`agents.form.analytics.topicModes.${topicMode}`)}
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                  </FormField>
                  {mode === 'auto' && autoTopics && (
                    <AutoTopics topics={autoTopics} />
                  )}
                </div>

                {mode === 'custom' && (
                  <div
                    className="flex flex-col gap-3"
                    data-testid="analytics-topics"
                  >
                    <SectionHeader
                      as="h3"
                      size="xs"
                      title={t('agents.form.analytics.customTopics')}
                      count={countOf(topics.length, maxTopics)}
                      actions={
                        !disabled && topics.length < maxTopics ? (
                          <>
                            {agentId && (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                loading={suggesting}
                                onClick={suggest}
                              >
                                {t('agents.form.analytics.suggest')}
                              </Button>
                            )}
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                setEditing({ kind: 'topic', index: null })
                              }
                            >
                              <Plus />
                              {t('agents.form.analytics.addTopic')}
                            </Button>
                          </>
                        ) : undefined
                      }
                    />
                    {suggestNote && (
                      <Alert variant="info" role="status">
                        <AlertDescription>
                          {t(SUGGEST_NOTE_KEYS[suggestNote])}
                        </AlertDescription>
                      </Alert>
                    )}
                    <Card
                      variant="subtle"
                      padding="none"
                      className="overflow-hidden"
                    >
                      {topics.length > 0 ? (
                        <ListRows>
                          {topics.map((topic, index) => (
                            <ListRow
                              key={topic.name}
                              title={topic.name}
                              description={topic.description || undefined}
                              trailing={itemMenu(
                                topic.name,
                                () => setEditing({ kind: 'topic', index }),
                                // Topic history is keyed by name: adding it
                                // back restores it, so no confirm.
                                () =>
                                  setTopics(
                                    topics.filter((_, i) => i !== index),
                                  ),
                              )}
                            />
                          ))}
                        </ListRows>
                      ) : (
                        <EmptyState
                          size="xs"
                          illustration="none"
                          title={t('agents.form.analytics.topicsEmpty')}
                        />
                      )}
                    </Card>
                  </div>
                )}

                {maxTags > 0 && (
                  <div
                    className="flex flex-col gap-3"
                    data-testid="analytics-tags"
                  >
                    <div className="flex flex-col gap-1.5">
                      <SectionHeader
                        as="h3"
                        size="xs"
                        title={t('agents.form.analytics.tags')}
                        count={countOf(tags.length, maxTags)}
                        actions={
                          !disabled && tags.length < maxTags ? (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() =>
                                setEditing({ kind: 'tag', index: null })
                              }
                            >
                              <Plus />
                              {t('agents.form.analytics.addTag')}
                            </Button>
                          ) : undefined
                        }
                      />
                      <p className="text-muted-foreground text-xs">
                        {t('agents.form.analytics.tagsDescription')}
                      </p>
                    </div>
                    <Card
                      variant="subtle"
                      padding="none"
                      className="overflow-hidden"
                    >
                      {tags.length > 0 ? (
                        <ListRows>
                          {tags.map((tag, index) => (
                            <ListRow
                              key={tag.id}
                              title={tag.name}
                              description={tag.description}
                              trailing={itemMenu(
                                tag.name,
                                () => setEditing({ kind: 'tag', index }),
                                () => setRemovingTag(tag),
                              )}
                            />
                          ))}
                        </ListRows>
                      ) : (
                        <EmptyState
                          size="xs"
                          illustration="none"
                          title={t('agents.form.analytics.tagsEmpty')}
                        />
                      )}
                    </Card>
                  </div>
                )}

                <SettingRow
                  label={t('agents.form.analytics.digest')}
                  description={t('agents.form.analytics.digestDescription')}
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
          </div>
        </Collapsible>
      </div>

      <AnalyticsItemModal
        kind={editing?.kind ?? 'topic'}
        item={editingItem}
        others={others}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSubmit={saveItem}
      />
      <ConfirmationModal
        message={t('agents.form.analytics.removeTag.title', {
          name: removingTag?.name ?? '',
          interpolation: { escapeValue: false },
        })}
        description={t('agents.form.analytics.removeTag.description')}
        modalState={removingTag ? 'ACTIVE' : 'INACTIVE'}
        setModalState={(state: ActiveState) => {
          if (state === 'INACTIVE') setRemovingTag(null);
        }}
        submitLabel={t('agents.form.analytics.removeTag.submit')}
        handleSubmit={() => {
          if (removingTag)
            setTags(tags.filter((tag) => tag.id !== removingTag.id));
          setRemovingTag(null);
        }}
        cancelLabel={t('cancel')}
        variant="destructive"
      />
    </Card>
  );
}

/**
 * The topics "From sources" will ask about, as the owner's folder names; with
 * fewer than two there is nothing to sort questions into.
 */
function AutoTopics({ topics }: { topics: AnalyticsTopic[] }) {
  const { t } = useTranslation();
  if (topics.length < MIN_AUTO_TOPICS)
    return (
      <p className="text-muted-foreground text-xs">
        {t('agents.form.analytics.autoTopicsNone')}
      </p>
    );
  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      data-testid="analytics-auto-topics"
    >
      <span className="text-muted-foreground text-xs">
        {t('agents.form.analytics.autoTopics')}
      </span>
      {topics.map((topic) => (
        <Badge key={topic.name} variant="neutral">
          {topic.name}
        </Badge>
      ))}
    </div>
  );
}
