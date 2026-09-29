import { Info, TriangleAlert, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';

import { can, isOwner } from '../../utils/accessUtils';
import type { Agent, ResourceSponsor } from '../types';

type SponsoredResourcesNoticeProps = {
  agent: Agent;
  /** Display name of a sponsored tool, source or prompt. */
  resolveName: (sponsor: ResourceSponsor) => string;
};

/** Sponsored items grouped by the person who added them, in first-seen order. */
function groupByPerson(sponsors: ResourceSponsor[]) {
  const groups = new Map<string, ResourceSponsor[]>();
  for (const sponsor of sponsors) {
    const key = sponsor.label || sponsor.user_id;
    groups.set(key, [...(groups.get(key) ?? []), sponsor]);
  }
  return Array.from(groups.entries());
}

/**
 * Tools, sources and prompts on the agent that run with an editor's access
 * rather than the owner's (`resource_sponsors` from GET /api/get_agent).
 *
 * An editor sees up front that what they attach runs with their access for
 * everyone who uses the agent. Everyone who may view the config sees who
 * added what, and which items no longer run because that person lost access.
 */
export default function SponsoredResourcesNotice({
  agent,
  resolveName,
}: SponsoredResourcesNoticeProps) {
  const { t } = useTranslation();
  const sponsors = agent.resource_sponsors ?? [];
  const showAttachNote = !isOwner(agent) && can(agent, 'edit');
  const active = groupByPerson(sponsors.filter((s) => s.active));
  const inactive = groupByPerson(sponsors.filter((s) => !s.active));

  if (!showAttachNote && sponsors.length === 0) return null;

  const names = (items: ResourceSponsor[]) =>
    items.map((item) => resolveName(item)).join(', ');

  return (
    <div className="flex flex-col gap-3 sm:col-span-2">
      {showAttachNote && (
        <Alert role="note">
          <Info />
          <AlertDescription>
            {t('agents.form.sponsors.attachNote')}
            {agent.shared ? ` ${t('agents.form.sponsors.publicLinkNote')}` : ''}
          </AlertDescription>
        </Alert>
      )}
      {active.length > 0 && (
        <Alert role="note">
          <UserRound />
          <AlertDescription>
            {active.map(([person, items]) => (
              <p key={person}>
                {t('agents.form.sponsors.addedBy', {
                  person,
                  names: names(items),
                })}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
      {inactive.length > 0 && (
        <Alert variant="warning">
          <TriangleAlert />
          <AlertDescription>
            {inactive.map(([person, items]) => (
              <p key={person}>
                {t('agents.form.sponsors.unavailable', {
                  person,
                  names: names(items),
                })}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
