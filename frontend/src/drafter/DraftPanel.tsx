import { ArrowUp, CircleCheck, Square, WandSparkles } from 'lucide-react';
import {
  type MouseEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';
import { Spinner } from '@/components/ui/spinner';
import { Textarea } from '@/components/ui/textarea';

import type { DrafterCounts, DrafterErrorCode } from './drafterApi';
import { DrafterQuestions } from './DrafterQuestions';
import type { DrafterItem, DrafterSession } from './useDrafterSession';

/** Where the footer's model note links: the task model lives on General. */
export const TASK_MODEL_SETTINGS_PATH = '/settings/general';

// The order the "Looked at your workspace" line lists counts in.
const COUNT_KEYS = ['sources', 'tools', 'prompts', 'models', 'agents'] as const;

// Errors a second try can fix; the others need a setting changed first.
const RETRYABLE: DrafterErrorCode[] = [
  'rate_limited',
  'invalid_output',
  'model_error',
];

export type DraftPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: DrafterSession;
  /** The task model's name for the footer; null hides the model part. */
  modelName: string | null;
  /** The first message before anything is sent. */
  intro: string;
  /** Example requests under the intro; a click puts one in the ask bar. */
  examples?: string[];
  /** Renders a proposal item (the recipe's summary). */
  renderProposal: (proposal: unknown, latest: boolean) => ReactNode;
  /**
   * The footer link's click handler, so a builder can ask before leaving
   * unsaved work (useLeaveGuard's `onNavigate()`).
   */
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
};

/**
 * The drafter's docked side panel ("Draft with DocsGPT"), the same for every
 * recipe: the intro and examples, the conversation (the user's messages, the
 * workspace line, the model's messages, its questions, each proposal through
 * `renderProposal`), errors with Retry, and an ask bar with Send or Stop. On
 * a phone the docked panel is a sheet.
 */
export function DraftPanel({
  open,
  onOpenChange,
  session,
  modelName,
  intro,
  examples = [],
  renderProposal,
  onNavigate,
}: DraftPanelProps) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const { items, step, streaming } = session;

  // Follow the conversation as it grows.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' });
  }, [items.length, step]);

  const send = () => {
    if (streaming || !draft.trim()) return;
    session.send(draft);
    setDraft('');
  };

  // The last proposal is the one Undo all applies to, and only questions not
  // followed by a user message can still be answered.
  const lastProposal = items.findLastIndex((item) => item.kind === 'proposal');
  const lastUser = items.findLastIndex((item) => item.kind === 'user');

  const renderItem = (item: DrafterItem, index: number) => {
    switch (item.kind) {
      case 'user':
        return (
          <p
            key={item.id}
            data-item="user"
            className="bg-secondary text-foreground ml-8 self-end rounded-2xl px-4 py-2.5 text-sm wrap-break-word whitespace-pre-wrap"
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
          />
        );
      case 'proposal':
        return (
          <div key={item.id} data-item="proposal">
            {renderProposal(item.proposal, index === lastProposal)}
          </div>
        );
      case 'error':
        return (
          <Alert key={item.id} variant="destructive" data-item="error">
            <AlertTitle>{t(`drafter.errors.${item.code}.title`)}</AlertTitle>
            <AlertDescription>
              <p>{t(`drafter.errors.${item.code}.description`)}</p>
              {RETRYABLE.includes(item.code) && index === items.length - 1 && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  shape="pill"
                  className="mt-2"
                  onClick={session.retry}
                >
                  {t('drafter.retry')}
                </Button>
              )}
            </AlertDescription>
          </Alert>
        );
    }
  };

  return (
    <SidePanel variant="docked" open={open} onOpenChange={onOpenChange}>
      <PanelHeader
        title={t('drafter.title')}
        leading={
          <WandSparkles
            className="text-link mt-0.5 size-5 shrink-0"
            aria-hidden="true"
          />
        }
      />
      <PanelBody>
        <div className="flex flex-col gap-4" aria-live="polite">
          {items.length === 0 && (
            <div className="flex flex-col gap-3">
              <p className="text-sm">{intro}</p>
              {examples.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {examples.map((example) => (
                    <Button
                      key={example}
                      type="button"
                      variant="outline"
                      size="sm"
                      shape="pill"
                      onClick={() => {
                        setDraft(example);
                        inputRef.current?.focus();
                      }}
                    >
                      {example}
                    </Button>
                  ))}
                </div>
              )}
            </div>
          )}
          {items.map(renderItem)}
          {step && (
            <p
              className="text-muted-foreground flex items-center gap-2 text-sm"
              data-slot="drafter-step"
            >
              <Spinner size="xs" label={t(`drafter.steps.${step}`)} />
              {t(`drafter.steps.${step}`)}
            </p>
          )}
          <div ref={endRef} />
        </div>
      </PanelBody>
      <PanelFooter>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex items-end gap-2">
            <Textarea
              ref={inputRef}
              rows={2}
              resize="none"
              className="min-h-16"
              value={draft}
              aria-label={t('drafter.askLabel')}
              placeholder={
                items.length === 0
                  ? t('drafter.startPlaceholder')
                  : t('drafter.askPlaceholder')
              }
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
            {streaming ? (
              <IconButton
                variant="outline"
                shape="pill"
                label={t('drafter.stop')}
                icon={Square}
                onClick={session.stop}
              />
            ) : (
              <IconButton
                shape="pill"
                label={t('drafter.send')}
                icon={ArrowUp}
                disabled={!draft.trim()}
                onClick={send}
              />
            )}
          </div>
          <p className="text-muted-foreground text-xs">
            {modelName
              ? t('drafter.footer', {
                  model: modelName,
                  interpolation: { escapeValue: false },
                })
              : t('drafter.footerNoModel')}{' '}
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

/** "Looked at your workspace", with what it counted. */
function WorkspaceLine({ counts }: { counts: DrafterCounts }) {
  const { t } = useTranslation();
  const parts = COUNT_KEYS.filter((key) => typeof counts[key] === 'number').map(
    (key) => t(`drafter.counts.${key}`, { count: counts[key] }),
  );
  return (
    <div data-item="status" className="flex items-start gap-2 text-sm">
      <CircleCheck
        className="text-success mt-0.5 size-4 shrink-0"
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-col">
        <span>{t('drafter.lookedAtWorkspace')}</span>
        {parts.length > 0 && (
          <span className="text-muted-foreground text-xs">
            {parts.join(' · ')}
          </span>
        )}
      </div>
    </div>
  );
}
