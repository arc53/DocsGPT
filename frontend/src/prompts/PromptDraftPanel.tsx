import {
  CircleHelp,
  Lightbulb,
  type LucideIcon,
  ScanSearch,
  WrapText,
} from 'lucide-react';
import type { MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { DraftPanel, type DraftPanelHelpers } from '../drafter/DraftPanel';
import { readPromptProposal } from '../drafter/promptDraft';
import { DRAFTER_STARTERS } from '../drafter/starters';
import type { PromptDrafter } from '../drafter/usePromptDrafter';
import SuggestionRows, { suggestionIconClass } from '../hero/SuggestionRows';
import { formatCount } from '../utils/dateTimeUtils';

// The first screen's rows. Improve's send their text; "Look it over" asks
// for an improvement with no particular change in mind. Write's are starting
// points: each sends its title and its id, and the drafter asks the rest.
const IMPROVE_SUGGESTIONS: { key: string; Icon: LucideIcon }[] = [
  { key: 'lookOver', Icon: ScanSearch },
  { key: 'clearer', Icon: WrapText },
  { key: 'unsure', Icon: CircleHelp },
];

/** The drawer's Save prompt: the view's own Save. */
export type PromptDraftSave = {
  onSave: () => void;
  disabled: boolean;
  saving: boolean;
};

type PromptDraftPanelProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  drafter: PromptDrafter;
  /** `improve` a prompt with text, `write` an empty one. */
  mode: 'improve' | 'write';
  /** The agents using the prompt: a saved change reaches them all. */
  usedBy: number;
  /** The task model's name for the footer; null hides it. */
  modelName: string | null;
  /** The footer link's click handler, to ask before leaving unsaved work. */
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
  /** Save prompt under a written draft. */
  save: PromptDraftSave;
};

/**
 * The prompt view's docked drawer: the DraftPanel running the prompt
 * recipe. Its greeting and rows follow the mode: a new prompt starts from
 * one of three starting points (or a description), and the drafter may ask
 * first, with Skip to draft at once. Each result shows its message, a
 * written prompt's reason, "Check before you save" warnings and the guesses
 * it made (I assumed, each with Change, which puts it in the ask bar); the
 * latest written prompt asks to be read and offers Save prompt, and the
 * latest improvement under review gets Accept all, Review one by one and
 * Discard. The per-change Accept and Reject stay inline in the editor's
 * review. The latest result ends with the model's next changes as rows.
 */
export function PromptDraftPanel({
  open,
  onOpenChange,
  drafter,
  mode,
  usedBy,
  modelName,
  onNavigate,
  save,
}: PromptDraftPanelProps) {
  const { t } = useTranslation();
  const usage = { count: usedBy, formatted: formatCount(usedBy) };
  const intro =
    mode === 'write'
      ? t('drafter.prompt.introWrite')
      : usedBy > 0
        ? t('drafter.prompt.introImproveUsedBy', usage)
        : t('drafter.prompt.introImprove');
  const suggestions =
    mode === 'write'
      ? DRAFTER_STARTERS.map(({ key, Icon }) => {
          const text = t(`drafter.starters.${key}.title`);
          return {
            key,
            icon: <Icon className={suggestionIconClass} aria-hidden="true" />,
            text,
            description: t(`drafter.starters.${key}.description`),
            onSelect: () => drafter.start(key, text),
          };
        })
      : IMPROVE_SUGGESTIONS.map(({ key, Icon }) => ({
          key,
          icon: <Icon className={suggestionIconClass} aria-hidden="true" />,
          text: t(`drafter.prompt.suggestions.${key}`),
        }));

  const renderProposal = (
    raw: unknown,
    latest: boolean,
    { compose }: DraftPanelHelpers,
  ): ReactNode => {
    const proposal = readPromptProposal(raw);
    if (!proposal) return null;
    const { review, session } = drafter;
    const reviewing = latest && review !== null && proposal.mode === 'improve';
    const written = latest && proposal.mode === 'write';
    // Next changes wait for an open review to end: sending one would end it.
    const next =
      latest && review === null && !session.streaming
        ? proposal.suggestions
        : [];
    return (
      <PromptResult
        message={proposal.message}
        reason={proposal.mode === 'write' ? proposal.reason : undefined}
        warnings={[
          ...proposal.checks.map((code) => t(`drafter.prompt.checks.${code}`)),
          ...proposal.warnings,
        ]}
        assumptions={proposal.mode === 'write' ? proposal.assumptions : []}
        onChangeAssumption={(assumption) =>
          compose(
            t('drafter.prompt.changeAssumptionPrefill', {
              assumption,
              interpolation: { escapeValue: false },
            }),
          )
        }
        next={next}
        onNext={(text) => session.send(text)}
        actions={
          written ? (
            <>
              <p className="text-sm">{t('drafter.prompt.readAndSave')}</p>
              <Button
                type="button"
                size="sm"
                shape="pill"
                disabled={save.disabled}
                loading={save.saving}
                onClick={save.onSave}
              >
                {t('drafter.prompt.savePrompt')}
              </Button>
            </>
          ) : reviewing ? (
            <>
              <Button
                type="button"
                size="sm"
                shape="pill"
                onClick={drafter.acceptAll}
              >
                {t('drafter.prompt.acceptAll')}
              </Button>
              {review.current === null && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  shape="pill"
                  onClick={drafter.reviewOneByOne}
                >
                  {t('drafter.prompt.reviewOneByOne')}
                </Button>
              )}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                shape="pill"
                onClick={drafter.discard}
              >
                {t('drafter.prompt.discard')}
              </Button>
            </>
          ) : undefined
        }
      />
    );
  };

  return (
    <DraftPanel
      open={open}
      onOpenChange={onOpenChange}
      session={drafter.session}
      modelName={modelName}
      onNavigate={onNavigate}
      intro={intro}
      suggestions={suggestions}
      placeholder={
        mode === 'write'
          ? t('drafter.prompt.writePlaceholder')
          : t('drafter.prompt.improvePlaceholder')
      }
      renderProposal={renderProposal}
      onSkipQuestions={
        mode === 'write'
          ? () => drafter.skipQuestions(t('drafter.prompt.skipMessage'))
          : undefined
      }
      announceProposal={(raw) => readPromptProposal(raw)?.message || null}
    />
  );
}

/**
 * One result in the drawer, in ProposalSummary's shapes: the message and a
 * written prompt's reason as paragraphs, what to check before saving as a
 * warning Alert, the guesses made (each with Change), the turn's actions,
 * and the next changes to send as suggestion rows last.
 */
function PromptResult({
  message,
  reason,
  warnings,
  assumptions,
  onChangeAssumption,
  next,
  onNext,
  actions,
}: {
  message: string;
  reason?: string;
  warnings: string[];
  assumptions: string[];
  onChangeAssumption: (assumption: string) => void;
  next: string[];
  onNext: (text: string) => void;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-2" data-slot="prompt-result">
      {[message, reason].filter(Boolean).map((text, index) => (
        <p key={index} className="text-sm wrap-break-word whitespace-pre-wrap">
          {text}
        </p>
      ))}
      {warnings.length > 0 && (
        <Alert
          variant="warning"
          role="status"
          data-slot="prompt-draft-warnings"
        >
          <AlertTitle>{t('drafter.prompt.warningsTitle')}</AlertTitle>
          <AlertDescription>
            <ul className="flex list-disc flex-col gap-1 pl-4">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {assumptions.length > 0 && (
        <div
          className="flex flex-col gap-1"
          data-slot="prompt-draft-assumptions"
        >
          <p className="text-sm font-medium">
            {t('drafter.prompt.assumptionsTitle')}
          </p>
          <ul className="flex list-disc flex-col gap-1 pl-4 text-sm">
            {assumptions.map((assumption) => (
              <li key={assumption} className="wrap-break-word">
                {assumption}{' '}
                <Button
                  type="button"
                  variant="link"
                  size="text"
                  aria-label={t('drafter.prompt.changeAssumptionLabel', {
                    assumption,
                    interpolation: { escapeValue: false },
                  })}
                  onClick={() => onChangeAssumption(assumption)}
                >
                  {t('drafter.prompt.changeAssumption')}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {actions && (
        <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div>
      )}
      {next.length > 0 && (
        <div className="flex flex-col gap-1 pt-1" data-slot="prompt-draft-next">
          <p className="text-muted-foreground text-sm">
            {t('drafter.prompt.nextTitle')}
          </p>
          <SuggestionRows
            label={t('drafter.prompt.nextTitle')}
            className="-mx-3"
            rows={next.map((text, index) => ({
              key: `next-${index}`,
              icon: (
                <Lightbulb className={suggestionIconClass} aria-hidden="true" />
              ),
              text,
              asks: true,
              onSelect: () => onNext(text),
            }))}
          />
        </div>
      )}
    </div>
  );
}
