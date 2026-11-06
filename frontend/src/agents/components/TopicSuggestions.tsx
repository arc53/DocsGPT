import { CircleCheck, WandSparkles } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { Spinner } from '@/components/ui/spinner';

import { DrafterErrorAlert } from '../../drafter/DrafterErrorAlert';
import {
  getTopicsStatus,
  parseTopicsProposal,
  type TopicsProposal,
  type TopicsStatus,
  type TopicSuggestion,
} from '../../drafter/topicsDraft';
import type { DrafterConfig } from '../../drafter/drafterApi';
import { loadDrafterConfig } from '../../drafter/useDrafterConfig';
import { useDrafterSession } from '../../drafter/useDrafterSession';
import { formatShare, joinList } from '../../settings/insights/format';
import { formatCount } from '../../utils/dateTimeUtils';
import {
  descriptionMax,
  nameTaken,
  topicsOfKind,
  units,
  visibleFolders,
} from '../analyticsConfig';
import type { AnalyticsConfig, TopicFolder } from '../types';
import type { TopicDraft } from './TopicModal';

export type TopicSuggestionsOptions = {
  /** The saved agent; suggestions need one. */
  agentId?: string;
  /** The settings can be edited and are on screen with insights on. */
  enabled: boolean;
  /** The session token, from the host. */
  token: string | null;
  config: AnalyticsConfig;
  /** The agent's source folders once loaded, largest first; null before. */
  folders: TopicFolder[] | null;
  maxTopics: number;
  maxOverlapping: number;
  /** Adds the picked topics through the host's own topic-add path. */
  onAdd: (topics: TopicDraft[]) => void;
};

export type TopicSuggestions = {
  /** "Suggest from conversations", or null while it can't be offered. */
  button: React.ReactNode;
  /**
   * Why the button isn't there yet (too few conversations), or that the
   * status couldn't be read, with Retry; null otherwise.
   */
  hold: React.ReactNode;
  /** The running or finished suggestions, inline above the topics; null when closed. */
  panel: React.ReactNode;
};

/** The drafter's config while `wanted`; null before it is read. */
function useDrafterConfigFor(
  wanted: boolean,
  token: string | null,
): DrafterConfig | null {
  const [config, setConfig] = React.useState<{
    token: string | null;
    value: DrafterConfig;
  } | null>(null);
  React.useEffect(() => {
    if (!wanted) return;
    let cancelled = false;
    void loadDrafterConfig(token).then((value) => {
      if (!cancelled) setConfig({ token, value });
    });
    return () => {
      cancelled = true;
    };
  }, [wanted, token]);
  return wanted && config?.token === token ? config.value : null;
}

/**
 * The agent's suggestion status, read while `agentId` is set: null before it
 * is read and when the suggestions aren't for this caller; `failed` when it
 * couldn't be read, until `retry` reads it again.
 */
function useTopicsStatus(
  agentId: string | null,
  token: string | null,
): { status: TopicsStatus | null; failed: boolean; retry: () => void } {
  const [attempt, setAttempt] = React.useState(0);
  const [read, setRead] = React.useState<{
    agentId: string;
    attempt: number;
    value: TopicsStatus | null;
    failed: boolean;
  } | null>(null);
  React.useEffect(() => {
    if (!agentId) return;
    const controller = new AbortController();
    getTopicsStatus(agentId, token, controller.signal).then(
      (value) => {
        if (!controller.signal.aborted)
          setRead({ agentId, attempt, value, failed: false });
      },
      () => {
        if (!controller.signal.aborted)
          setRead({ agentId, attempt, value: null, failed: true });
      },
    );
    return () => controller.abort();
  }, [agentId, token, attempt]);
  const current = read && read.agentId === agentId ? read : null;
  return {
    status: current?.value ?? null,
    // A retry under way shows nothing until it answers.
    failed: current?.failed === true && current.attempt === attempt,
    retry: () => setAttempt((n) => n + 1),
  };
}

/**
 * "Suggest from conversations" on an agent's Insights topics: Draft with
 * DocsGPT reads the agent's recent questions and suggests topics that cover
 * them. Offered only on a saved agent the caller can edit, with the drafter
 * on and enough recent conversations; until then `hold` says how many it
 * takes, the way Insights holds a figure until it has enough data. Picked
 * suggestions go through `onAdd`, the host's own topic-add path, so nothing
 * is saved until the host saves. It reads the token from the host, not the
 * store, and the drafting session lives in the panel, mounted only while it
 * is open.
 *
 * Args:
 *   options: The agent, its settings and folders, the limits and `onAdd`.
 *
 * Returns:
 *   The button, the hold line and the inline panel, each null when not shown.
 */
export function useTopicSuggestions({
  agentId,
  enabled,
  token,
  config,
  folders,
  maxTopics,
  maxOverlapping,
  onAdd,
}: TopicSuggestionsOptions): TopicSuggestions {
  const { t } = useTranslation();
  const wanted = enabled && !!agentId;
  const drafter = useDrafterConfigFor(wanted, token);
  const offered = wanted && drafter?.enabled === true;
  const { status, failed, retry } = useTopicsStatus(
    offered && agentId ? agentId : null,
    token,
  );
  const [open, setOpen] = React.useState(false);
  // The panel closes for good when it stops being offered (the section folds,
  // insights go off, a save is under way): mounting it again would start a
  // new turn the user didn't ask for.
  if (open && !offered) setOpen(false);

  const close = () => setOpen(false);
  const start = () => setOpen(true);

  const room =
    topicsOfKind(config, false).length < maxTopics ||
    topicsOfKind(config, true).length < maxOverlapping;
  const ready = offered && status?.available === true;
  const button =
    ready && room && !open ? (
      <Button
        type="button"
        variant="outline-primary"
        size="sm"
        shape="pill"
        data-drafter-entry=""
        onClick={start}
      >
        <WandSparkles />
        {t('drafter.topics.suggest')}
      </Button>
    ) : null;
  let hold: React.ReactNode = null;
  if (offered && failed)
    hold = (
      <>
        {t('drafter.topics.statusFailed')}{' '}
        <Button type="button" variant="link" size="text" onClick={retry}>
          {t('retry')}
        </Button>
      </>
    );
  // Off (the drafter or Insights) offers nothing; too few conversations says how many it takes.
  else if (offered && status && !status.available && !status.reason)
    hold = t('drafter.topics.hold', {
      count: status.needed,
      needed: formatCount(status.needed),
      formatted: formatCount(status.conversations),
    });
  const panel =
    open && offered && agentId ? (
      <TopicSuggestionsCard
        agentId={agentId}
        config={config}
        folders={folders}
        maxTopics={maxTopics}
        maxOverlapping={maxOverlapping}
        onDiscard={close}
        onAdd={(topics) => {
          onAdd(topics);
          close();
        }}
      />
    ) : null;
  return { button, hold, panel };
}

type CardProps = {
  agentId: string;
  config: AnalyticsConfig;
  folders: TopicFolder[] | null;
  maxTopics: number;
  maxOverlapping: number;
  onDiscard: () => void;
  onAdd: (topics: TopicDraft[]) => void;
};

/**
 * The suggestions inline in the topics area: what was read, each suggestion
 * with a checkbox (on by default), its description, the share of questions
 * it would get (marked when estimated rather than measured), its budget and
 * kind, a warning when it is close to a topic the agent has; then what was
 * left out, what adding pushes out, and Discard / Add N topics. Mounting it
 * starts the one drafting turn; unmounting stops it.
 */
export function TopicSuggestionsCard({
  agentId,
  config,
  folders,
  maxTopics,
  maxOverlapping,
  onDiscard,
  onAdd,
}: CardProps) {
  const { t } = useTranslation();
  const session = useDrafterSession({
    recipe: 'topics',
    getContext: () => ({ agent_id: agentId }),
    onProposal: () => undefined,
  });
  const { items, streaming, reset, send } = session;
  const request = React.useRef(t('drafter.topics.request'));
  React.useEffect(() => {
    // Reset first: under StrictMode the first turn is stopped by the
    // simulated unmount, and the second starts from an empty history.
    reset();
    send(request.current);
  }, [reset, send]);
  const proposalItem = items.findLast((item) => item.kind === 'proposal');
  const proposal =
    proposalItem?.kind === 'proposal'
      ? parseTopicsProposal(proposalItem.proposal)
      : null;
  const last = items.at(-1);
  const error = last?.kind === 'error' ? last : null;
  const message = items.findLast((item) => item.kind === 'message');

  const discard = (
    <Button type="button" variant="ghost" size="sm" onClick={onDiscard}>
      {t('drafter.topics.discard')}
    </Button>
  );

  let body: React.ReactNode;
  if (streaming) {
    body = (
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <p
          className="text-muted-foreground flex items-center gap-2 text-sm"
          aria-live="polite"
        >
          <Spinner size="xs" label={t('drafter.topics.reading')} />
          {t('drafter.topics.reading')}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => {
            session.stop();
            onDiscard();
          }}
        >
          {t('cancel')}
        </Button>
      </div>
    );
  } else if (error) {
    body = (
      <div className="flex flex-col gap-3 p-4">
        <DrafterErrorAlert
          code={error.code}
          onRetry={session.retry}
          description={
            error.code === 'invalid_output' || error.code === 'model_error'
              ? t(`drafter.topics.errors.${error.code}`)
              : undefined
          }
        />
        <div className="flex justify-end">{discard}</div>
      </div>
    );
  } else if (proposal) {
    body = (
      <Suggestions
        key={proposalItem?.id}
        proposal={proposal}
        config={config}
        folders={folders}
        maxTopics={maxTopics}
        maxOverlapping={maxOverlapping}
        discard={discard}
        onAdd={onAdd}
      />
    );
  } else {
    // The model answered in plain text, or the turn was stopped.
    body = (
      <div className="flex flex-col gap-3 p-4">
        {message?.kind === 'message' && (
          <p className="text-sm whitespace-pre-wrap">{message.text}</p>
        )}
        <div className="flex justify-end">{discard}</div>
      </div>
    );
  }

  return (
    <Card
      variant="subtle"
      padding="none"
      className="gap-0 overflow-hidden"
      data-testid="topic-suggestions"
    >
      {body}
    </Card>
  );
}

function Suggestions({
  proposal,
  config,
  folders,
  maxTopics,
  maxOverlapping,
  discard,
  onAdd,
}: {
  proposal: TopicsProposal;
  config: AnalyticsConfig;
  folders: TopicFolder[] | null;
  maxTopics: number;
  maxOverlapping: number;
  discard: React.ReactNode;
  onAdd: (topics: TopicDraft[]) => void;
}) {
  const { t } = useTranslation();
  const baseId = React.useId();
  const { sample, topics } = proposal;

  // A name taken since the suggestions came (a topic added by hand) can't be added.
  const view = visibleFolders(folders ?? [], config, maxTopics);
  const taken = [
    ...config.topics.map((topic) => topic.name),
    ...(folders ?? []).map((folder) => folder.name),
  ];
  const isTaken = (topic: TopicSuggestion) => nameTaken(topic.name, taken);
  const [picked, setPicked] = React.useState<Set<string>>(
    () =>
      new Set(
        topics.filter((topic) => !isTaken(topic)).map((topic) => topic.id),
      ),
  );
  const chosen = topics.filter(
    (topic) => picked.has(topic.id) && !isTaken(topic),
  );
  const onePick = chosen.filter((topic) => !topic.overlap);
  const overlapping = chosen.filter((topic) => topic.overlap);
  // A limit lowered below the topics the agent has leaves no room (the
  // server keeps those it has), not less than none.
  const onePickRoom = Math.max(
    0,
    maxTopics - topicsOfKind(config, false).length,
  );
  const overlapRoom = Math.max(
    0,
    maxOverlapping - topicsOfKind(config, true).length,
  );

  // What the picked topics push out of the topic question: worked out from
  // the folders when they are loaded, else from the server's list.
  let pushed: string[];
  if (folders) {
    const after = visibleFolders(
      folders,
      {
        ...config,
        topics: [
          ...config.topics,
          ...onePick.map((topic) => ({ ...topic, overlap: false })),
        ],
      },
      maxTopics,
    ).shown.map((folder) => folder.name);
    pushed = view.shown
      .map((folder) => folder.name)
      .filter((name) => !after.includes(name));
  } else {
    const over = Math.max(
      0,
      onePick.length - proposal.capacity.one_per_question_free,
    );
    pushed = over > 0 ? proposal.capacity.pushes_out.slice(-over) : [];
  }

  const notes: { key: string; text: string }[] = [];
  if (proposal.left_out.length > 0)
    notes.push({
      key: 'leftOut',
      text: t('drafter.topics.leftOut', {
        items: joinList(
          proposal.left_out.map((item) =>
            item.reason
              ? t('drafter.topics.leftOutItem', {
                  name: item.name,
                  reason: item.reason,
                  interpolation: { escapeValue: false },
                })
              : item.name,
          ),
        ),
        interpolation: { escapeValue: false },
      }),
    });
  if (pushed.length > 0)
    notes.push({
      key: 'pushesOut',
      text: t('drafter.topics.pushesOut', {
        count: pushed.length,
        names: joinList(pushed),
        interpolation: { escapeValue: false },
      }),
    });
  const overOnePick = onePick.length > onePickRoom;
  const overOverlap = overlapping.length > overlapRoom;
  if (overOnePick)
    notes.push({
      key: 'tooManyOnePick',
      text: t('drafter.topics.tooManyOnePick', {
        count: onePickRoom,
        formatted: formatCount(onePickRoom),
      }),
    });
  if (overOverlap)
    notes.push({
      key: 'tooManyOverlap',
      text: t('drafter.topics.tooManyOverlap', {
        count: overlapRoom,
        formatted: formatCount(overlapRoom),
      }),
    });

  const unmatched = sample.unmatched;
  const tried =
    unmatched && unmatched.after !== null
      ? unmatched.before !== null
        ? t('drafter.topics.tried', {
            count: unmatched.questions,
            formatted: formatCount(unmatched.questions),
            after: formatShare(unmatched.after),
            before: formatShare(unmatched.before),
          })
        : t('drafter.topics.triedAfter', {
            count: unmatched.questions,
            formatted: formatCount(unmatched.questions),
            after: formatShare(unmatched.after),
          })
      : null;

  const toggle = (id: string, on: boolean) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <>
      <div className="flex flex-col gap-2 px-4 py-3">
        <div
          data-item="status"
          className="flex items-start gap-2 text-sm"
          aria-live="polite"
        >
          <CircleCheck
            className="text-success mt-0.5 size-4 shrink-0"
            aria-hidden="true"
          />
          <div className="flex min-w-0 flex-col">
            <span>
              {t('drafter.topics.read', {
                count: sample.questions,
                formatted: formatCount(sample.questions),
                days: formatCount(sample.days),
              })}
            </span>
            {tried && (
              <span className="text-muted-foreground text-xs">{tried}</span>
            )}
          </div>
        </div>
        {proposal.message && (
          <p className="text-sm whitespace-pre-wrap">{proposal.message}</p>
        )}
      </div>

      {topics.length === 0 ? (
        <p className="text-muted-foreground border-t px-4 py-3 text-sm">
          {t('drafter.topics.none')}
        </p>
      ) : (
        <ul className="divide-border divide-y border-t">
          {topics.map((topic) => {
            const id = `${baseId}-${topic.id}`;
            const max = descriptionMax(topic.overlap);
            const off = isTaken(topic);
            return (
              <li
                key={topic.id}
                data-suggestion={topic.id}
                className="flex items-start gap-3 px-4 py-3"
              >
                <Checkbox
                  id={id}
                  className="mt-0.5"
                  checked={!off && picked.has(topic.id)}
                  disabled={off}
                  onCheckedChange={(checked) =>
                    toggle(topic.id, checked === true)
                  }
                />
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <Label htmlFor={id} className="wrap-break-word">
                    {topic.name}
                  </Label>
                  {topic.description && (
                    <p className="text-muted-foreground text-sm wrap-break-word">
                      {topic.description}
                    </p>
                  )}
                  <div className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    {topic.share !== null && (
                      <span className="flex items-center gap-2">
                        <Progress
                          value={topic.share * 100}
                          variant="muted"
                          size="sm"
                          className="w-16"
                          aria-hidden="true"
                        />
                        {t('drafter.topics.share', {
                          share: formatShare(topic.share),
                        })}
                      </span>
                    )}
                    {topic.share !== null &&
                      topic.share_kind === 'estimate' && (
                        <Badge
                          variant="neutral"
                          title={t('drafter.topics.estimateHint')}
                        >
                          {t('drafter.topics.estimate')}
                        </Badge>
                      )}
                    <span className="tabular-nums">
                      {t('agents.form.analytics.countOf', {
                        count: formatCount(Math.ceil(units(topic.description))),
                        max: formatCount(max),
                      })}
                    </span>
                    <span>
                      {topic.overlap
                        ? t('agents.form.analytics.groups.overlap')
                        : t('agents.form.analytics.groups.onePick')}
                    </span>
                    {off && <span>{t('drafter.topics.taken')}</span>}
                  </div>
                  {topic.similar_to ? (
                    <Alert variant="warning" className="mt-1">
                      <AlertDescription>
                        {[
                          t('drafter.topics.similar', {
                            name: topic.similar_to,
                            interpolation: { escapeValue: false },
                          }),
                          topic.note,
                        ]
                          .filter(Boolean)
                          .join(' ')}
                      </AlertDescription>
                    </Alert>
                  ) : (
                    topic.note && (
                      <p className="text-muted-foreground text-xs">
                        {topic.note}
                      </p>
                    )
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {notes.length > 0 && (
        <div className="divide-y border-t">
          {notes.map((note) => (
            <p
              key={note.key}
              data-note={note.key}
              className="text-muted-foreground px-4 py-2.5 text-xs"
            >
              {note.text}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-end gap-2 border-t px-4 py-3">
        {discard}
        {topics.length > 0 && (
          <Button
            type="button"
            size="sm"
            disabled={chosen.length === 0 || overOnePick || overOverlap}
            onClick={() =>
              onAdd(
                chosen.map((topic) => ({
                  name: topic.name,
                  description: topic.description,
                  overlap: topic.overlap,
                })),
              )
            }
          >
            {t('drafter.topics.add', {
              count: chosen.length,
              formatted: formatCount(chosen.length),
            })}
          </Button>
        )}
      </div>
    </>
  );
}
