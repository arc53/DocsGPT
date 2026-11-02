import {
  Ban,
  BookOpen,
  Headset,
  Languages,
  type LucideIcon,
  ScanSearch,
} from 'lucide-react';
import type { MouseEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { DraftPanel } from '../drafter/DraftPanel';
import { readPromptProposal } from '../drafter/promptDraft';
import type { PromptDrafter } from '../drafter/usePromptDrafter';
import { suggestionIconClass } from '../hero/SuggestionRows';
import { formatCount } from '../utils/dateTimeUtils';

// The first screen's rows; each sends its text. "Look it over" asks for an
// improvement with no particular change in mind.
const IMPROVE_SUGGESTIONS: { key: string; Icon: LucideIcon }[] = [
  { key: 'lookOver', Icon: ScanSearch },
  { key: 'noPrices', Icon: Ban },
  { key: 'language', Icon: Languages },
];
const WRITE_SUGGESTIONS: { key: string; Icon: LucideIcon }[] = [
  { key: 'handbook', Icon: BookOpen },
  { key: 'support', Icon: Headset },
];

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
};

/**
 * The prompt view's docked drawer: the DraftPanel running the prompt
 * recipe. Its greeting and suggestion rows follow the mode; each result
 * shows its message, a written prompt's reason and "Check before you save"
 * warnings, and the latest improvement under review gets Accept all, Review
 * one by one and Discard. The per-change Accept and Reject stay inline in
 * the editor's review.
 */
export function PromptDraftPanel({
  open,
  onOpenChange,
  drafter,
  mode,
  usedBy,
  modelName,
  onNavigate,
}: PromptDraftPanelProps) {
  const { t } = useTranslation();
  const usage = { count: usedBy, formatted: formatCount(usedBy) };
  const intro =
    mode === 'write'
      ? t('drafter.prompt.introWrite')
      : usedBy > 0
        ? t('drafter.prompt.introImproveUsedBy', usage)
        : t('drafter.prompt.introImprove');
  const suggestions = (
    mode === 'write' ? WRITE_SUGGESTIONS : IMPROVE_SUGGESTIONS
  ).map(({ key, Icon }) => ({
    key,
    icon: <Icon className={suggestionIconClass} aria-hidden="true" />,
    text: t(`drafter.prompt.suggestions.${key}`),
  }));

  const renderProposal = (raw: unknown, latest: boolean): ReactNode => {
    const proposal = readPromptProposal(raw);
    if (!proposal) return null;
    const { review } = drafter;
    const reviewing = latest && review !== null && proposal.mode === 'improve';
    return (
      <PromptResult
        message={proposal.message}
        reason={proposal.mode === 'write' ? proposal.reason : undefined}
        warnings={[
          ...proposal.checks.map((code) => t(`drafter.prompt.checks.${code}`)),
          ...proposal.warnings,
        ]}
        actions={
          reviewing ? (
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
      announceProposal={(raw) => readPromptProposal(raw)?.message || null}
    />
  );
}

/**
 * One result in the drawer, in ProposalSummary's shapes: the message and a
 * written prompt's reason as paragraphs, what to check before saving as a
 * warning Alert, and the turn's actions last.
 */
function PromptResult({
  message,
  reason,
  warnings,
  actions,
}: {
  message: string;
  reason?: string;
  warnings: string[];
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
      {actions && <div className="flex flex-wrap gap-2 pt-1">{actions}</div>}
    </div>
  );
}
