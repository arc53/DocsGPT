import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import PageToolbar from '../../components/PageToolbar';
import { formatDateTime } from '../../utils/dateTimeUtils';

type AgentPageToolbarProps = {
  /** The agent's name, first in the byline. */
  name?: string;
  /** A status Badge beside the name (Overview's Published / Draft). */
  status?: ReactNode;
  /** The tab's context after the name, e.g. "Last used at …". */
  meta?: ReactNode;
  /** The tab's buttons, on the right of the row. */
  actions?: ReactNode;
  /** A line of its own in place of the name byline (the new-agent form). */
  intro?: ReactNode;
  /** Notices under the row, above the rule (a failed save). */
  children?: ReactNode;
};

/**
 * The block under an agent tab's title (Overview, Logs, Schedules): a muted
 * byline naming the agent, the tab's actions on the right, then a rule. The
 * row keeps the field height when a tab has no actions, so the rule lands in
 * the same place on every tab and nothing jumps when switching.
 *
 * Args:
 *   name: The agent's name.
 *   status: A Badge shown beside the name.
 *   meta: Tab context shown after the name, separated by a middle dot.
 *   actions: The tab's buttons.
 *   intro: Replaces the name byline.
 *   children: Notices between the row and the rule.
 */
export default function AgentPageToolbar({
  name,
  status,
  meta,
  actions,
  intro,
  children,
}: AgentPageToolbarProps) {
  const byline = intro ?? (
    <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
      {name ? <span className="wrap-break-word">{name}</span> : null}
      {status}
      {meta ? (
        status ? (
          // With a status badge the first line is full on a phone: the meta
          // takes its own line there, so no separator is left hanging.
          <>
            <span aria-hidden className="hidden sm:inline">
              ·
            </span>
            <span className="basis-full sm:basis-auto">{meta}</span>
          </>
        ) : (
          <>
            <span aria-hidden>·</span>
            <span>{meta}</span>
          </>
        )
      ) : null}
    </span>
  );

  return (
    <PageToolbar
      intro={byline}
      action={actions ?? <div aria-hidden className="h-9.5" />}
      divider
    >
      {children}
    </PageToolbar>
  );
}

/**
 * The agent tabs' usage meta: "Last used at …", or "no usage history".
 *
 * Args:
 *   lastUsedAt: The agent's `last_used_at` timestamp.
 */
export function LastUsedMeta({ lastUsedAt }: { lastUsedAt?: string | null }) {
  const { t } = useTranslation();
  return (
    <>
      {lastUsedAt
        ? `${t('agents.logs.lastUsedAt')} ${formatDateTime(lastUsedAt)}`
        : t('agents.logs.noUsageHistory')}
    </>
  );
}
