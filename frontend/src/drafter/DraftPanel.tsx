import {
  ArrowUp,
  ChartNoAxesColumn,
  MessagesSquare,
  RotateCcw,
  ScanSearch,
  WandSparkles,
} from 'lucide-react';
import {
  Fragment,
  type MouseEvent,
  type ReactNode,
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';
import { flushSync } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import isEqual from 'lodash/isEqual';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import { Progress } from '@/components/ui/progress';
import { SectionHeader } from '@/components/ui/section-header';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';
import { cn } from '@/lib/utils';

import { QuestionCards } from '../components/QuestionCards';
import StreamingStatusLine from '../conversation/StreamingStatusLine';
import SuggestionRows from '../hero/SuggestionRows';
import { useMediaQuery } from '../hooks';
import { formatCount } from '../utils/dateTimeUtils';

import { type DrafterCounts, DRAFTER_USER_MESSAGE_CHARS } from './drafterApi';
import {
  DrafterErrorAlert,
  TASK_MODEL_SETTINGS_PATH,
} from './DrafterErrorAlert';
import { DrafterStepRow, FilledRow } from './DrafterStepRow';
import type { DrafterItem, DrafterSession } from './useDrafterSession';
import { wandEntry } from './WandButton';

/** The window Insights reads over when the host doesn't say (agent_gaps' `days`). */
const INSIGHTS_DAYS = 30;

/** The footer's line, by what the recipe reads, with a model and without. */
const FOOTER_KEYS = {
  workspace: ['drafter.footer', 'drafter.footerNoModel'],
  prompt: ['drafter.footerPrompt', 'drafter.footerPromptNoModel'],
  insights: ['drafter.footerInsights', 'drafter.footerInsightsNoModel'],
  promptAgents: [
    'drafter.footerPromptAgents',
    'drafter.footerPromptAgentsNoModel',
  ],
} as const;

// The order the "Looked at your workspace" line lists counts in.
const COUNT_KEYS = ['sources', 'tools', 'prompts', 'models', 'agents'] as const;

// Where the footer's model note links: the task model lives on General.
export { RETRYABLE, TASK_MODEL_SETTINGS_PATH } from './DrafterErrorAlert';

/**
 * A first-screen suggestion: a click sends its text, or runs `onSelect`
 * when the host sends it itself (a starter that adds to the context).
 */
export type DraftSuggestion = {
  key: string;
  icon: ReactNode;
  text: string;
  description?: string;
  onSelect?: () => void;
};

/** A titled group of first-screen suggestions ("From its conversations"). */
export type DraftSuggestionGroup = {
  key: string;
  title: string;
  /** A muted tally after the title ("last 30 days"). */
  count?: string;
  rows: DraftSuggestion[];
};

/** What a rendered proposal can do in the panel. */
export type DraftPanelHelpers = {
  /** Put `text` in the ask bar and focus it, for the user to finish. */
  compose: (text: string) => void;
  /**
   * Run a button's action that takes the button away (Accept all,
   * Discard), then, if focus dropped to <body>, move it on to the panel's
   * `data-drafter-next-focus` control or else the ask bar (on a desktop).
   */
  keepFocus: (action: () => void) => void;
};

export type DraftPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: DrafterSession;
  /** The task model's name for the footer; null hides the model part. */
  modelName: string | null;
  /**
   * What the footer says the recipe reads: the workspace (agents, knowledge,
   * tools and prompts; the default), the workspace and the agent's Insights,
   * or only the prompt being drafted.
   */
  reads?: 'workspace' | 'prompt' | 'insights';
  /**
   * With `reads="prompt"`: how many agents use the prompt, which the recipe
   * reads too ("reads this prompt and the 3 agents using it").
   */
  readsAgents?: number;
  /**
   * The days Insights reads over, for a `reading` status that read it
   * ("Read Insights: 412 conversations, last 30 days").
   */
  insightsDays?: number;
  /**
   * The footer link's click handler, so a builder can ask before leaving
   * unsaved work (useLeaveGuard's `onNavigate()`).
   */
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** The greeting before anything is sent. */
  intro: string;
  /** Suggestion rows under the greeting; a click sends the row's text. */
  suggestions?: DraftSuggestion[];
  /**
   * Suggestions in titled groups, in place of `suggestions` (an improve's
   * rows from Insights, then those from the agent's setup).
   */
  suggestionGroups?: DraftSuggestionGroup[];
  /** Under the first screen's rows: a note on what it can't read, say. */
  notice?: ReactNode;
  /**
   * Where a guided build stands: the header's description is `label` and a
   * small bar under it shows `value` (0 to 100).
   */
  progress?: { label: string; value: number } | null;
  /** Above the conversation: the finished steps, folded. */
  before?: ReactNode;
  /**
   * The status line's text for the running turn in place of the step's
   * ("Reviewing the prompt…" for a prompt review).
   */
  statusLabel?: string;
  /** The ask bar's placeholder; "Ask for a change…" when left out. */
  placeholder?: string;
  /** Renders a proposal item (the recipe's summary). */
  renderProposal: (
    proposal: unknown,
    latest: boolean,
    helpers: DraftPanelHelpers,
  ) => ReactNode;
  /**
   * When given, open questions offer Skip, which calls it instead of
   * sending answers.
   */
  onSkipQuestions?: () => void;
  /**
   * What a screen reader hears once the latest proposal is applied ("Drafted
   * 3 fields…"); null announces nothing.
   */
  announceProposal?: (proposal: unknown) => string | null;
  /**
   * The way on after a turn was stopped or failed (a build's "Continue:
   * Basics"): on its own row under the latest error, and under the stopped
   * note while it is the latest. It
   * keeps its own look: it is a way past the error, not a fix, so it never
   * sits in the Alert.
   */
  continueAction?: ReactNode;
  /**
   * After the conversation while no turn runs: what the host adds at the
   * end of a turn of its own (the saved prompt's Filled rows and Next).
   */
  after?: ReactNode;
  /**
   * Starts the conversation over (the host's own reset). Given, the header
   * offers Start over once anything was sent; a full or refused
   * conversation offers it either way, with the session's reset when left
   * out.
   */
  onStartOver?: () => void;
};

/**
 * The drafter's docked side panel ("Draft with DocsGPT"), the same for every
 * recipe, drawn in the chat's shapes: the greeting and suggestion rows, the
 * conversation (the user's bubbles, the workspace line, the model's
 * messages, its questions, each proposal through `renderProposal`), the
 * running step on the chat's status line, errors with Retry, and the chat
 * composer's frame with Send or Stop. A conversation as long as the server
 * takes, or one it refused, offers Start over. A guided build adds its
 * progress to the header, its finished steps above the conversation, its way
 * on after a Stop or an error, and its own turn ends after it. On a phone the
 * docked panel is a sheet.
 */
export function DraftPanel({
  open,
  onOpenChange,
  session,
  modelName,
  reads = 'workspace',
  readsAgents = 0,
  insightsDays = INSIGHTS_DAYS,
  onNavigate,
  intro,
  suggestions = [],
  suggestionGroups,
  notice,
  progress,
  before,
  statusLabel,
  placeholder,
  renderProposal,
  onSkipQuestions,
  announceProposal,
  continueAction,
  after,
  onStartOver,
}: DraftPanelProps) {
  const { t } = useTranslation();
  const { isDesktop, isMobile } = useMediaQuery();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wasOpen = useRef(false);
  const [draft, setDraft] = useState('');
  const helpers: DraftPanelHelpers = {
    compose: (text) => {
      setDraft(text);
      inputRef.current?.focus();
    },
    keepFocus: (action) => {
      const scope =
        endRef.current?.closest<HTMLElement>('[data-slot="side-panel"]') ??
        endRef.current?.parentElement;
      flushSync(action);
      const active = document.activeElement;
      if (active && active !== document.body && active.isConnected) return;
      const next = scope?.querySelector<HTMLElement>(
        '[data-drafter-next-focus]',
      );
      if (next) next.focus();
      else if (isDesktop) inputRef.current?.focus();
    },
  };
  const { items, step, streaming, waiting, full } = session;
  const startOver = () => (onStartOver ?? session.reset)();
  // Start over fixes a full or refused conversation, so it is a link in
  // the notice's own text.
  const startOverLink = (
    <Button
      type="button"
      variant="link"
      size="text"
      tone="current"
      onClick={startOver}
    >
      {t('drafter.startOver')}
    </Button>
  );
  const bodyRef = useRef<HTMLDivElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  // The body was scrolled to its end: what renders late (a review's
  // actions, a field opening in a question) keeps the end in view.
  const atEnd = useRef(true);
  const toEnd = () => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
    atEnd.current = true;
  };

  // The open round of questions, still waiting for answers.
  const openQuestions = () =>
    columnRef.current?.querySelector<HTMLElement>(
      '[data-item="questions"][data-open]',
    ) ?? null;

  // Follow the conversation as it grows, and land on its end on reopening.
  // A turn that ends on questions lands on the first of them when they
  // don't all fit.
  useEffect(() => {
    if (!open) return;
    toEnd();
    if (!streaming && items.at(-1)?.kind === 'questions') {
      openQuestions()?.querySelector('[data-question]')?.scrollIntoView?.({
        block: 'nearest',
      });
    }
  }, [items.length, step, open]);

  useEffect(() => {
    const body = bodyRef.current;
    const column = columnRef.current;
    if (!open || !body || !column) return;
    const onScroll = () => {
      atEnd.current =
        body.scrollTop + body.clientHeight >= body.scrollHeight - 24;
    };
    body.addEventListener('scroll', onScroll, { passive: true });
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            if (atEnd.current) toEnd();
          });
    observer?.observe(column);
    return () => {
      body.removeEventListener('scroll', onScroll);
      observer?.disconnect();
    };
  }, [open]);

  // Focus never drops to <body> in the docked panel (a sheet keeps it
  // itself): a send whose button goes (Send answers, a starter) or a Stop
  // moves it to the ask bar, and a turn that ends on questions to the first
  // of them, also from an empty ask bar. Only while focus was last in the
  // panel: a click in the page leaves it there.
  const focusWasHere = useRef(false);
  useEffect(() => {
    if (!open) return;
    const panel = () => endRef.current?.closest('[data-slot="side-panel"]');
    const onFocusIn = (event: FocusEvent) => {
      focusWasHere.current = !!panel()?.contains(event.target as Node);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (!panel()?.contains(event.target as Node))
        focusWasHere.current = false;
    };
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('pointerdown', onPointerDown);
    return () => {
      document.removeEventListener('focusin', onFocusIn);
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, [open]);
  useEffect(() => {
    if (!open || isMobile || !focusWasHere.current) return;
    const active = document.activeElement;
    const lost = !active || active === document.body;
    const input = inputRef.current;
    const questions = streaming ? null : openQuestions();
    const first = questions?.querySelector<HTMLElement>(
      '[role="radio"], [role="checkbox"], input',
    );
    // A typed question's field would raise a tablet's keyboard.
    const canFocus = first && (isDesktop || first.tagName !== 'INPUT');
    if (canFocus && (lost || (active === input && !input?.value))) {
      first.focus();
    } else if (lost && isDesktop) input?.focus();
  }, [streaming, items.length]);

  // Opening the docked panel beside the form puts the cursor in its ask bar;
  // not on a phone or tablet, where a keyboard would cover the sheet.
  useEffect(() => {
    if (open && !wasOpen.current && isDesktop) inputRef.current?.focus();
    wasOpen.current = open;
  }, [open, isDesktop]);

  const lastProposal = items.findLastIndex((item) => item.kind === 'proposal');
  const latestProposal = items[lastProposal];
  const announcement =
    latestProposal?.kind === 'proposal' && announceProposal
      ? announceProposal(latestProposal.proposal)
      : null;

  // A prompt's drawer that reads the agents using it says how many.
  const readsPromptAgents = reads === 'prompt' && readsAgents > 0;
  const footerKeys = FOOTER_KEYS[readsPromptAgents ? 'promptAgents' : reads];
  const agentsRead = readsPromptAgents
    ? { count: readsAgents, formatted: formatCount(readsAgents) }
    : undefined;

  // A suggestion sends its text, unless the host runs it itself.
  const toRow = (suggestion: DraftSuggestion) => ({
    ...suggestion,
    asks: true,
    onSelect: suggestion.onSelect ?? (() => session.send(suggestion.text)),
  });

  // "Looked at your workspace" once, and again only when the counts change.
  const repeatsCounts = (index: number) => {
    const item = items[index];
    if (item.kind !== 'status') return false;
    const earlier = items.findLast(
      (other, at) => at < index && other.kind === 'status',
    );
    return earlier?.kind === 'status' && isEqual(earlier.counts, item.counts);
  };

  const renderItem = (item: DrafterItem, index: number) => {
    switch (item.kind) {
      case 'user':
        return (
          <p
            key={item.id}
            data-item="user"
            className="bg-secondary text-foreground ml-8 self-end rounded-3xl px-5 py-4 text-sm leading-normal wrap-break-word whitespace-pre-wrap"
          >
            {item.text}
          </p>
        );
      case 'status':
        if (repeatsCounts(index)) return null;
        return typeof item.counts.insights_conversations === 'number' ? (
          <div key={item.id} className="flex flex-col gap-1">
            <WorkspaceLine counts={item.counts} />
            <InsightsLine
              count={item.counts.insights_conversations}
              days={insightsDays}
            />
          </div>
        ) : (
          <WorkspaceLine key={item.id} counts={item.counts} />
        );
      case 'read':
        // End users' questions, shown as the text they are.
        return (
          <div key={item.id} data-item="read">
            <DrafterStepRow
              icon={MessagesSquare}
              label={t('drafter.readQuestions', { count: item.items.length })}
            >
              {item.items.map((question, at) => (
                <FilledRow key={at} value={question} />
              ))}
            </DrafterStepRow>
          </div>
        );
      case 'message':
        return (
          <p
            key={item.id}
            data-item="message"
            className="text-sm wrap-break-word whitespace-pre-wrap"
          >
            {item.text}
          </p>
        );
      case 'questions':
        // Open until a message passes it; then the cards are the record (no
        // bubble repeats the answers), a blank one reads Skipped, and a round
        // passed over reads Not answered.
        return (
          <div
            key={item.id}
            data-item="questions"
            data-open={item.state ? undefined : ''}
          >
            <QuestionCards
              questions={item.questions}
              active={!streaming && !item.state}
              onAnswer={(message, answers) =>
                session.send(message, { answers })
              }
              onSkip={
                onSkipQuestions &&
                (() => {
                  session.closeQuestions('skipped');
                  onSkipQuestions();
                })
              }
              skipLabel={t('drafter.skipQuestions')}
              answers={item.answers ?? (item.state ? {} : undefined)}
              emptyLabel={
                item.state === 'passed' ? undefined : t('questions.skipped')
              }
            />
          </div>
        );
      case 'proposal':
        return (
          <div key={item.id} data-item="proposal">
            {renderProposal(item.proposal, index === lastProposal, helpers)}
          </div>
        );
      case 'stopped':
        // The chat's stopped note; the way on goes under it while it is the
        // latest, and the note stays as the record after it.
        return (
          <Fragment key={item.id}>
            <Alert variant="info" role="note" data-item="stopped">
              <AlertTitle>{t('conversation.stoppedTitle')}</AlertTitle>
              <AlertDescription>
                <p>{t('drafter.stoppedDescription')}</p>
              </AlertDescription>
            </Alert>
            {index === items.length - 1 && !streaming && continueAction && (
              <div className="flex flex-wrap gap-2" data-slot="drafter-stopped">
                {continueAction}
              </div>
            )}
          </Fragment>
        );
      case 'error': {
        // A refused request (the history too long, say) fails again as it
        // is: only a fresh conversation goes on.
        const refused = item.code === 'bad_request';
        const latest = index === items.length - 1;
        // The way on isn't a fix for the error, so it goes under the Alert.
        return (
          <Fragment key={item.id}>
            <DrafterErrorAlert
              code={item.code}
              description={
                refused ? t('drafter.errors.bad_request.startOver') : undefined
              }
              onRetry={latest ? session.retry : undefined}
              fix={latest && refused ? startOverLink : undefined}
              model={modelName}
              onNavigate={onNavigate}
            />
            {latest && continueAction && (
              <div
                className="flex flex-wrap gap-2"
                data-slot="drafter-continue"
              >
                {continueAction}
              </div>
            )}
          </Fragment>
        );
      }
    }
  };

  return (
    <SidePanel
      variant="docked"
      open={open}
      onOpenChange={onOpenChange}
      focusFallback={wandEntry}
    >
      <PanelHeader
        title={t('drafter.title')}
        description={progress?.label}
        leading={
          <WandSparkles
            className="text-link mt-0.5 size-5 shrink-0"
            aria-hidden="true"
          />
        }
        actions={
          onStartOver && items.length > 0 ? (
            <IconButton
              variant="ghost-muted"
              size="icon-sm"
              side="bottom"
              label={t('drafter.startOver')}
              icon={RotateCcw}
              onClick={startOver}
            />
          ) : undefined
        }
      >
        {progress && (
          <Progress
            size="sm"
            value={progress.value}
            aria-label={t('drafter.title')}
            getValueLabel={() => progress.label}
          />
        )}
      </PanelHeader>
      <PanelBody ref={bodyRef}>
        <div ref={columnRef} className="flex flex-col gap-4">
          {before}
          {items.length === 0 && !streaming && (
            <div className="flex flex-col gap-3">
              {intro && (
                <p className="text-sm wrap-break-word whitespace-pre-wrap">
                  {intro}
                </p>
              )}
              {suggestionGroups ? (
                <div className="flex flex-col gap-4">
                  {suggestionGroups.map((group) => (
                    <div key={group.key} className="flex flex-col gap-1">
                      <SectionHeader
                        as="h3"
                        size="xs"
                        title={group.title}
                        count={group.count}
                      />
                      <SuggestionRows
                        label={group.title}
                        className="-mx-3"
                        rows={group.rows.map(toRow)}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <SuggestionRows
                  label={t('drafter.suggestionsLabel')}
                  className="-mx-3"
                  rows={suggestions.map(toRow)}
                />
              )}
              {notice}
            </div>
          )}
          {items.map(renderItem)}
          {!streaming && after}
          {full && !streaming && (
            <Alert variant="info" data-slot="drafter-full">
              <AlertTitle>{t('drafter.full.title')}</AlertTitle>
              <AlertDescription>
                <p>
                  {t('drafter.full.description')} {startOverLink}
                </p>
              </AlertDescription>
            </Alert>
          )}
          {step && (
            <div className="flex flex-col">
              <StreamingStatusLine
                label={statusLabel ?? t(`drafter.steps.${step}`)}
              />
              {waiting && (
                // Aligned with the status line's text, past its 16px dot.
                <p
                  data-slot="drafter-waiting"
                  className="text-muted-foreground pl-6 text-xs wrap-break-word"
                >
                  {t('drafter.stillWaiting')}
                </p>
              )}
            </div>
          )}
          {/* The status line announces the step; this announces each
              applied draft, not the whole conversation as it grows. */}
          <div ref={endRef} aria-live="polite" data-slot="drafter-live">
            {announcement && latestProposal && (
              <p key={latestProposal.id} className="sr-only">
                {announcement}
              </p>
            )}
          </div>
        </div>
      </PanelBody>
      <PanelFooter>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <Composer
            inputRef={inputRef}
            draft={draft}
            setDraft={setDraft}
            streaming={streaming}
            disabled={full}
            placeholder={placeholder ?? t('drafter.askPlaceholder')}
            onSend={(text) => session.send(text)}
            onStop={session.stop}
          />
          {/* text-pretty keeps "Change model" from ending alone on a line. */}
          <p className="text-muted-foreground text-xs text-pretty">
            {modelName
              ? t(footerKeys[0], {
                  model: modelName,
                  ...agentsRead,
                  interpolation: { escapeValue: false },
                })
              : t(footerKeys[1], agentsRead)}{' '}
            <Button variant="link" size="text" asChild>
              <Link to={TASK_MODEL_SETTINGS_PATH} onClick={onNavigate}>
                {t('drafter.changeModel')}
              </Link>
            </Button>
          </p>
        </div>
      </PanelFooter>
    </SidePanel>
  );
}

/**
 * The ask bar in the chat composer's frame (MessageInput's): a borderless
 * textarea that grows from one line to six, and the composer's round button
 * in the corner, grey while empty, Send with text, Stop (a filled square)
 * while a turn runs. Enter sends, Shift+Enter breaks the line; a message
 * stops at the server's length, and a full conversation takes none. Kept here
 * rather than shared: MessageInput's frame also carries attachments, voice
 * and the source and tool pickers.
 */
function Composer({
  inputRef,
  draft,
  setDraft,
  streaming,
  disabled,
  placeholder,
  onSend,
  onStop,
}: {
  inputRef: RefObject<HTMLTextAreaElement | null>;
  /** The ask bar's text, held by the panel so a proposal can prefill it. */
  draft: string;
  setDraft: (draft: string) => void;
  streaming: boolean;
  /** No message can go (the conversation is full). */
  disabled: boolean;
  placeholder: string;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const { t } = useTranslation();
  const empty = !draft.trim() || disabled;

  // Grow with the text; max-h-36 (six lines) caps it, then it scrolls.
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${input.scrollHeight}px`;
  }, [draft, inputRef]);

  const send = () => {
    if (streaming || empty) return;
    onSend(draft);
    setDraft('');
  };

  return (
    <div className="border-border bg-card focus-within:border-ring focus-within:ring-ring/50 relative flex w-full flex-col rounded-3xl border transition-shadow focus-within:ring-3">
      <textarea
        ref={inputRef}
        rows={1}
        value={draft}
        maxLength={DRAFTER_USER_MESSAGE_CHARS}
        disabled={disabled}
        aria-label={t('drafter.askLabel')}
        placeholder={placeholder}
        className="text-foreground placeholder:text-muted-foreground max-h-36 w-full resize-none overflow-y-auto rounded-t-3xl bg-transparent px-4 pt-3 text-sm leading-6 outline-none"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (
            event.key === 'Enter' &&
            !event.shiftKey &&
            !event.nativeEvent.isComposing
          ) {
            event.preventDefault();
            send();
          }
        }}
      />
      <div className="flex items-center justify-end px-2 pb-2">
        {/* Keyed apart: Stop must not become a focused, disabled Send. */}
        {streaming ? (
          <IconButton
            key="stop"
            size="icon-sm"
            shape="pill"
            label={t('drafter.stop')}
            onClick={onStop}
          >
            <span className="bg-primary-foreground size-3 rounded-sm" />
          </IconButton>
        ) : (
          <IconButton
            key="send"
            size="icon-sm"
            shape="pill"
            label={t('drafter.send')}
            icon={ArrowUp}
            disabled={empty}
            onClick={send}
            className={cn(
              empty &&
                /* eslint-disable-next-line shadcn/no-restyle --
                   The empty composer's send button is a grey circle, as in
                   the chat composer: no variant is neutral while disabled. */
                'bg-muted text-muted-foreground dark:bg-accent',
            )}
          />
        )}
      </div>
    </div>
  );
}

/**
 * "Read Insights: 412 conversations, last 30 days", the workspace line's
 * twin under it when the turn read the agent's Insights.
 */
function InsightsLine({ count, days }: { count: number; days: number }) {
  const { t } = useTranslation();
  return (
    <div
      data-item="insights"
      className="text-muted-foreground flex items-start gap-2 text-sm"
    >
      <ChartNoAxesColumn
        className="mt-0.5 size-4 shrink-0"
        aria-hidden="true"
      />
      <p className="min-w-0 wrap-break-word">
        {t('drafter.readInsights', {
          count,
          formatted: formatCount(count),
          days,
        })}
      </p>
    </div>
  );
}

/** "Looked at your workspace: 6 knowledge sources · 11 tools", one muted line. */
function WorkspaceLine({ counts }: { counts: DrafterCounts }) {
  const { t } = useTranslation();
  const parts = COUNT_KEYS.filter((key) => typeof counts[key] === 'number').map(
    (key) => t(`drafter.counts.${key}`, { count: counts[key] }),
  );
  return (
    <div
      data-item="status"
      className="text-muted-foreground flex items-start gap-2 text-sm"
    >
      <ScanSearch className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <p className="min-w-0 wrap-break-word">
        {parts.length > 0
          ? t('drafter.lookedAtWorkspaceCounts', {
              counts: parts.join(' · '),
              interpolation: { escapeValue: false },
            })
          : t('drafter.lookedAtWorkspace')}
      </p>
    </div>
  );
}
