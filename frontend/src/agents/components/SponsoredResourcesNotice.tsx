import { Info, TriangleAlert, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { can, isOwner } from '../../utils/accessUtils';
import { intlLocale } from '../../utils/dateTimeUtils';
import type { Agent, ResourceSponsor } from '../types';

type SponsoredResourcesNoticeProps = {
  agent: Agent;
  /** Display name of a sponsored tool, source or prompt. */
  resolveName: (sponsor: ResourceSponsor) => string;
  /** Keys of stopped items the reader chose to run with their access on save. */
  takeovers?: string[];
  /** Turn a take-over on or off for one item's key. */
  onToggleTakeover?: (key: string) => void;
};

/** Why an item stopped, as the message key that says so. */
function stoppedMessageKey(sponsor: ResourceSponsor): string {
  if (sponsor.reason === 'sponsor_cannot_edit_agent')
    return 'agents.form.sponsors.stoppedCannotEditAgent';
  if (sponsor.reason === 'sponsor_cannot_edit_resource')
    return 'agents.form.sponsors.stoppedCannotEditItem';
  return 'agents.form.sponsors.unavailable';
}

/** Items grouped by the person who added them and ``extra``, in first-seen order. */
function groupByPerson(
  sponsors: ResourceSponsor[],
  extra: (sponsor: ResourceSponsor) => string = () => '',
) {
  const groups = new Map<string, ResourceSponsor[]>();
  for (const sponsor of sponsors) {
    const key = `${sponsor.label || sponsor.user_id}\u0000${extra(sponsor)}`;
    groups.set(key, [...(groups.get(key) ?? []), sponsor]);
  }
  return Array.from(groups.values());
}

const sponsorKey = (sponsor: ResourceSponsor) =>
  sponsor.key || `${sponsor.type}:${sponsor.id}`;

/**
 * Tools, sources and prompts on the agent that run with an editor's access
 * rather than the owner's (`resource_sponsors` from GET /api/get_agent).
 *
 * An editor sees up front that what they attach runs with their access for
 * everyone who uses the agent. Everyone who may edit the agent sees who added
 * what, and which items stopped and why. An item the reader may sponsor
 * (`can_confirm`) can be taken over: it then runs with the reader's access
 * from their next save.
 */
export default function SponsoredResourcesNotice({
  agent,
  resolveName,
  takeovers = [],
  onToggleTakeover,
}: SponsoredResourcesNoticeProps) {
  const { t, i18n } = useTranslation();
  const sponsors = agent.resource_sponsors ?? [];
  const showAttachNote = !isOwner(agent) && can(agent, 'edit');
  const active = groupByPerson(sponsors.filter((s) => s.active));
  const inactiveItems = sponsors.filter((s) => !s.active);
  const inactive = groupByPerson(inactiveItems, stoppedMessageKey);
  const claimable = onToggleTakeover
    ? inactiveItems.filter((s) => s.can_confirm)
    : [];

  if (!showAttachNote && sponsors.length === 0) return null;

  const listFormat = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  });
  const names = (items: ResourceSponsor[]) =>
    listFormat.format(items.map((item) => resolveName(item)));
  const person = (items: ResourceSponsor[]) =>
    items[0].label || items[0].user_id;

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
            {active.map((items) => (
              <p key={sponsorKey(items[0])}>
                {t('agents.form.sponsors.addedBy', {
                  interpolation: { escapeValue: false },
                  person: person(items),
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
            <div className="flex flex-col gap-2">
              {inactive.map((items) => (
                <p key={sponsorKey(items[0])}>
                  {t(stoppedMessageKey(items[0]), {
                    interpolation: { escapeValue: false },
                    person: person(items),
                    names: names(items),
                  })}
                </p>
              ))}
              {claimable.map((item) => {
                const key = sponsorKey(item);
                const name = resolveName(item);
                return takeovers.includes(key) ? (
                  <div
                    key={key}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1"
                  >
                    <span>
                      {t('agents.form.sponsors.takeOverPending', {
                        interpolation: { escapeValue: false },
                        name,
                      })}
                    </span>
                    <Button
                      type="button"
                      variant="link"
                      size="inline"
                      onClick={() => onToggleTakeover?.(key)}
                    >
                      {t('agents.form.sponsors.undoTakeOver')}
                    </Button>
                  </div>
                ) : (
                  <div key={key}>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      shape="pill"
                      onClick={() => onToggleTakeover?.(key)}
                    >
                      {t('agents.form.sponsors.takeOver', {
                        interpolation: { escapeValue: false },
                        name,
                      })}
                    </Button>
                  </div>
                );
              })}
            </div>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
