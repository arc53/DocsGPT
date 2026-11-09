import { ArrowRight } from 'lucide-react';
import type { MouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardTitle } from '@/components/ui/card';

import { FilledRow } from '../drafter/DrafterStepRow';
import { knowledgeLink } from '../settings/knowledgeLink';
import { logsDrilldownPath } from '../settings/logsLinks';
import {
  type AgentDraftField,
  type AgentGapLink,
  type AgentProposalGap,
  gapLine,
  gapTitle,
} from './agentDraft';

/**
 * The gaps an improve proposal acts on, one card each (`Card subtle sm`, the
 * drafter's card surface): the gap row's own title and line, the question it
 * read in quotes, a FilledRow per field its fix set, and what it can't fix
 * itself with links to where that's done (the source, the questions in
 * Logs), through the form's leave guard.
 *
 * Args:
 *   gaps: The proposal's gaps.
 *   agentId: The agent, for its Logs.
 *   fieldRow: The label and summary of a field the fix set; null leaves the
 *     field out (applying the draft didn't change it).
 *   onNavigate: A link's click handler (the leave guard's `onNavigate()`).
 */
export default function AgentGapCards({
  gaps,
  agentId,
  fieldRow,
  onNavigate,
}: {
  gaps: AgentProposalGap[];
  agentId: string;
  fieldRow: (
    field: AgentDraftField,
  ) => { label: string; summary: string } | null;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { t } = useTranslation();
  const linkOf = (link: AgentGapLink) =>
    link.kind === 'source'
      ? {
          to: knowledgeLink({ sourceId: link.id }),
          label: t('drafter.agent.insights.openSource', {
            name: link.name || t('drafter.agent.insights.theSource'),
            interpolation: { escapeValue: false },
          }),
        }
      : {
          to: logsDrilldownPath({ agentId, label: link.label }),
          label: t('drafter.agent.insights.seeInLogs'),
        };
  return (
    <div className="flex flex-col gap-2" data-slot="gap-cards">
      {gaps.map((gap, index) => {
        const rows = gap.fields.flatMap((field) => {
          const row = fieldRow(field);
          return row ? [{ field, ...row }] : [];
        });
        return (
          <Card
            key={`${gap.topic ?? ''}:${gap.gap_type}:${index}`}
            variant="subtle"
            padding="sm"
            className="gap-2"
            data-slot="gap-card"
          >
            <div className="flex flex-col gap-0.5">
              <CardTitle as="h3">{gapTitle(t, gap)}</CardTitle>
              <CardDescription size="xs" className="tabular-nums">
                {gapLine(t, gap)}
              </CardDescription>
            </div>
            {gap.example && (
              <p className="text-sm wrap-break-word">
                {t('drafter.agent.insights.quoted', {
                  text: gap.example,
                  interpolation: { escapeValue: false },
                })}
              </p>
            )}
            {rows.length > 0 && (
              <div className="flex min-w-0 flex-col">
                {rows.map((row) => (
                  <FilledRow
                    key={row.field}
                    label={row.label}
                    value={row.summary}
                  />
                ))}
              </div>
            )}
            {gap.needs && (
              <p className="text-sm wrap-break-word whitespace-pre-wrap">
                {gap.needs}
              </p>
            )}
            {gap.links.length > 0 && (
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                {gap.links.map((link, at) => {
                  const { to, label } = linkOf(link);
                  return (
                    <Button key={at} variant="link" size="inline" asChild>
                      <Link to={to} onClick={onNavigate}>
                        {label}
                        <ArrowRight />
                      </Link>
                    </Button>
                  );
                })}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
