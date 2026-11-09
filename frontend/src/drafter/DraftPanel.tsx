import { ArrowUp, RotateCcw, ScanSearch, WandSparkles } from 'lucide-react';
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
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import { Progress } from '@/components/ui/progress';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';
import { cn } from '@/lib/utils';

import StreamingStatusLine from '../conversation/StreamingStatusLine';
import SuggestionRows from '../hero/SuggestionRows';
import { useMediaQuery } from '../hooks';

import { type DrafterCounts, DRAFTER_USER_MESSAGE_CHARS } from './drafterApi';
import { DrafterErrorAlert } from './DrafterErrorAlert';
import { DrafterQuestions } from './DrafterQuestions';
import type { DrafterItem, DrafterSession } from './useDrafterSession';

/** Where the footer's model note links: the task model lives on General. */
export const TASK_MODEL_SETTINGS_PATH = '/settings/general';

// The order the "Looked at your workspace" line lists counts in.
const COUNT_KEYS = ['sources', 'tools', 'prompts', 'models', 'agents'] as const;

export { RETRYABLE } from './DrafterErrorAlert';

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

/** What a rendered proposal can do in the panel. */
export type DraftPanelHelpers = {
  /** Put `text` in the ask bar and focus it, for the user to finish. */
  compose: (text: string) => void;
};

export type DraftPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: DrafterSession;
  /** The task model's name for the footer; null hides the model part. */
  modelName: string | null;
  /**
   * What the footer says the recipe reads: the workspace (agents, knowledge,
   * tools and prompts; the default) or only the prompt being drafted.
   */
  reads?: 'workspace' | 'prompt';
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
   * Where a guided build stands: the header's description is `label` and a
   * small bar under it shows `value` (0 to 100).
   */
  progress?: { label: string; value: number } | null;
  /** Above the conversation: the finished steps, folded. */
  before?: ReactNode;
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
   * Basics"): on its own row under the latest error, and after Stop. It
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
  onNavigate,
  intro,
  suggestions = [],
  progress,
  before,
  placeholder,
  renderProposal,
  onSkipQuestions,
  announceProposal,
  continueAction,
  after,
  onStartOver,
}: DraftPanelProps) {
  const { t } = useTranslation();
  const { isDesktop } = useMediaQuery();
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const wasOpen = useRef(false);
  const [draft, setDraft] = useState('');
  const helpers: DraftPanelHelpers = {
    compose: (text) => {
      setDraft(text);
      inputRef.current?.focus();
    },
  };
  const { items, step, streaming, full } = session;
  const startOver = () => {
    setStopped(false);
    (onStartOver ?? session.reset)();
  };
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
  // The latest turn was stopped here: the way on shows until the next one.
  const [stopped, setStopped] = useState(false);
  useEffect(() => {
    if (streaming || items.length === 0) setStopped(false);
  }, [streaming, items.length]);

  // Follow the conversation as it grows, and land on its end on reopening.
  useEffect(() => {
    if (open) endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [items.length, step, open]);

  // Opening the docked panel beside the form puts the cursor in its ask bar;
  // not on a phone or tablet, where a keyboard would cover the sheet.
  useEffect(() => {
    if (open && !wasOpen.current && isDesktop) inputRef.current?.focus();
    wasOpen.current = open;
  }, [open, isDesktop]);

  // Only questions not followed by a user message can still be answered.
  const lastProposal = items.findLastIndex((item) => item.kind === 'proposal');
  const lastUser = items.findLastIndex((item) => item.kind === 'user');
  const latestProposal = items[lastProposal];
  const announcement =
    latestProposal?.kind === 'proposal' && announceProposal
      ? announceProposal(latestProposal.proposal)
      : null;

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
        return <WorkspaceLine key={item.id} counts={item.counts} />;
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
        return (
          <DrafterQuestions
            key={item.id}
            questions={item.questions}
            active={!streaming && index > lastUser}
            onAnswer={(message) => session.send(message)}
            onSkip={onSkipQuestions}
          />
        );
      case 'proposal':
        return (
          <div key={item.id} data-item="proposal">
            {renderProposal(item.proposal, index === lastProposal, helpers)}
          </div>
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
    <SidePanel variant="docked" open={open} onOpenChange={onOpenChange}>
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
      <PanelBody>
        <div className="flex flex-col gap-4">
          {before}
          {items.length === 0 && !streaming && (
            <div className="flex flex-col gap-3">
              <p className="text-sm wrap-break-word whitespace-pre-wrap">
                {intro}
              </p>
              <SuggestionRows
                label={t('drafter.suggestionsLabel')}
                className="-mx-3"
                rows={suggestions.map((suggestion) => ({
                  ...suggestion,
                  asks: true,
                  onSelect:
                    suggestion.onSelect ??
                    (() => session.send(suggestion.text)),
                }))}
              />
            </div>
          )}
          {items.map(renderItem)}
          {stopped && !streaming && continueAction && (
            <div className="flex flex-wrap gap-2" data-slot="drafter-stopped">
              {continueAction}
            </div>
          )}
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
          {step && <StreamingStatusLine label={t(`drafter.steps.${step}`)} />}
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
            onStop={() => {
              setStopped(true);
              session.stop();
            }}
          />
          <p className="text-muted-foreground text-xs">
            {modelName
              ? t(
                  reads === 'prompt'
                    ? 'drafter.footerPrompt'
                    : 'drafter.footer',
                  {
                    model: modelName,
                    interpolation: { escapeValue: false },
                  },
                )
              : t(
                  reads === 'prompt'
                    ? 'drafter.footerPromptNoModel'
                    : 'drafter.footerNoModel',
                )}{' '}
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
        {streaming ? (
          <IconButton
            size="icon-sm"
            shape="pill"
            label={t('drafter.stop')}
            onClick={onStop}
          >
            <span className="bg-primary-foreground size-3 rounded-sm" />
          </IconButton>
        ) : (
          <IconButton
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
