import { type ReactNode, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Collapsible, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ListRow, ListRows } from '@/components/ui/list-row';
import { SectionHeader } from '@/components/ui/section-header';

import type { ReviewCheck, ReviewFinding } from '../drafter/promptDraft';
import { promptCheckText } from './promptCheckText';

type PromptReviewFindingsProps = {
  findings: ReviewFinding[];
  passed: ReviewCheck[];
  /**
   * The number each change under review has in the editor (by edit id);
   * a finding whose change isn't under review has no "Change n".
   */
  changeNumbers: Record<string, number>;
  /** Step the editor's review to a change. */
  onChange: (editId: string) => void;
  /** Put a finding's prefill in the ask bar. */
  onAsk: (prefill: string) => void;
  /** Open an agent using the prompt; no "Open …" without it. */
  onOpenAgent?: (agent: { id: string; name: string }) => void;
};

/**
 * A prompt review's findings in the drawer: To fix, then
 * Worth a look, each a SectionHeader with its count over a subtle Card of
 * ListRows (the title, a muted detail, and one link at the end: "Change n"
 * to the change in the editor, the finding's ask, which prefills the ask
 * bar, or "Open {name}" for an agent using the prompt). The server's own
 * checks are worded here by code. The checks that pass fold under an inline
 * toggle, "All 9 checks pass" when nothing was found.
 */
export function PromptReviewFindings({
  findings,
  passed,
  changeNumbers,
  onChange,
  onAsk,
  onOpenAgent,
}: PromptReviewFindingsProps) {
  const { t } = useTranslation();
  const passedId = useId();
  const [passedOpen, setPassedOpen] = useState(false);

  const titleOf = (finding: ReviewFinding): ReactNode =>
    finding.source === 'server'
      ? (promptCheckText(t, {
          code: finding.code ?? '',
          text: finding.text,
          topic: finding.text,
        }) ?? finding.title)
      : finding.title;

  const linkOf = (finding: ReviewFinding) => {
    const number = finding.edit ? changeNumbers[finding.edit] : undefined;
    if (finding.edit && number !== undefined) {
      const edit = finding.edit;
      return (
        <Button
          type="button"
          variant="link"
          size="text"
          aria-label={t('drafter.prompt.review.changeLabel', { number })}
          onClick={() => onChange(edit)}
        >
          {t('drafter.prompt.review.change', { number })}
        </Button>
      );
    }
    if (finding.ask) {
      const { label, prefill } = finding.ask;
      return (
        <Button
          type="button"
          variant="link"
          size="text"
          onClick={() => onAsk(prefill)}
        >
          {label}
        </Button>
      );
    }
    if (finding.agent && onOpenAgent) {
      const agent = finding.agent;
      return (
        <Button
          type="button"
          variant="link"
          size="text"
          onClick={() => onOpenAgent(agent)}
        >
          {t('drafter.prompt.review.openAgent', {
            name: agent.name,
            interpolation: { escapeValue: false },
          })}
        </Button>
      );
    }
    return undefined;
  };

  const groups = (['fix', 'look'] as const)
    .map((severity) => ({
      severity,
      findings: findings.filter((finding) => finding.severity === severity),
    }))
    .filter((group) => group.findings.length > 0);

  return (
    <div className="flex flex-col gap-3" data-slot="prompt-review-findings">
      {groups.map(({ severity, findings: group }) => (
        <div
          key={severity}
          className="flex flex-col gap-2"
          data-severity={severity}
        >
          <SectionHeader
            as="h3"
            size="xs"
            title={
              severity === 'fix'
                ? t('drafter.prompt.review.toFix')
                : t('drafter.prompt.review.worthALook')
            }
            count={group.length}
          />
          <Card variant="subtle" padding="none">
            <ListRows>
              {group.map((finding) => (
                <ListRow
                  key={finding.id}
                  data-finding={finding.id}
                  wrap
                  title={titleOf(finding)}
                  description={finding.detail || undefined}
                  trailing={linkOf(finding)}
                />
              ))}
            </ListRows>
          </Card>
        </div>
      ))}
      {passed.length > 0 && (
        <div data-slot="prompt-review-passed">
          <CollapsibleTrigger
            open={passedOpen}
            onOpenChange={setPassedOpen}
            controls={passedId}
          >
            {findings.length === 0
              ? t('drafter.prompt.review.allPassed', { count: passed.length })
              : t('drafter.prompt.review.passed', { count: passed.length })}
          </CollapsibleTrigger>
          <Collapsible id={passedId} open={passedOpen}>
            <ul className="text-muted-foreground flex list-disc flex-col gap-1 pt-1 pl-4 text-sm">
              {passed.map((check) => (
                <li key={check}>
                  {t(`drafter.prompt.review.checks.${check}`)}
                </li>
              ))}
            </ul>
          </Collapsible>
        </div>
      )}
    </div>
  );
}
