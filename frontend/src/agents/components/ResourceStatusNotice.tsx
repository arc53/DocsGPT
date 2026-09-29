import { Info, TriangleAlert, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';

import { can, isOwner } from '../../utils/accessUtils';
import { intlLocale } from '../../utils/dateTimeUtils';
import type {
  Agent,
  ResourceSponsor,
  ResourceState,
  ResourceStateReason,
} from '../types';

/** What the notice needs to name an item. */
export type NamedResource = Pick<ResourceState, 'type' | 'id' | 'name'>;

type ResourceStatusNoticeProps = {
  /** The agent the page edits: the reader's access, its link, its sponsors. */
  agent: Agent;
  /** Stopped items still attached in the form (`resource_states`). */
  stopped: ResourceState[];
  /** Display name of a tool, source or prompt. */
  resolveName: (item: NamedResource) => string;
  /** Keys of stopped items the reader chose to run with their access on save. */
  takeovers?: string[];
  /** Ask the reader to run one item with their access. */
  onTakeOver?: (item: ResourceState) => void;
  /** Drop a pending take-over. */
  onUndoTakeover?: (key: string) => void;
  /** Take one item off the agent (or the workflow's nodes). */
  onRemove?: (item: ResourceState) => void;
  /** Sign the item's connection in again. */
  onReconnect?: (item: ResourceState) => void;
  /** Tell an editor that what they add runs with their access (the agent form). */
  showAttachNote?: boolean;
};

/** The message key that says why an item stopped. */
export function reasonKey(
  reason: ResourceStateReason | null,
  ownerReads: boolean,
) {
  switch (reason) {
    case 'deleted':
      return 'agents.form.resourceStates.reason.deleted';
    case 'owner_lost_access':
      return ownerReads
        ? 'agents.form.resourceStates.reason.ownerLostAccessYou'
        : 'agents.form.resourceStates.reason.ownerLostAccess';
    case 'sponsor_cannot_edit_agent':
      return 'agents.form.resourceStates.reason.sponsorCannotEditAgent';
    case 'sponsor_cannot_edit_resource':
      return 'agents.form.resourceStates.reason.sponsorCannotEditItem';
    case 'connection_needs_reconnect':
      return 'agents.form.resourceStates.reason.connectionNeedsReconnect';
    case 'connection_removed':
      return 'agents.form.resourceStates.reason.connectionRemoved';
    case 'connector_disabled':
      return 'agents.form.resourceStates.reason.connectorDisabled';
    default:
      return 'agents.form.resourceStates.reason.unknown';
  }
}

/** Whom to ask, as the key that says so; null when the reader can act. */
function askKey(item: ResourceState): string | null {
  if (item.reason === 'connector_disabled')
    return 'agents.form.resourceStates.ask.admin';
  if (!item.contact) return null;
  if (item.reason === 'owner_lost_access')
    return 'agents.form.resourceStates.ask.shareAgain';
  if (item.reason === 'connection_needs_reconnect')
    return 'agents.form.resourceStates.ask.signInAgain';
  if (item.reason === 'connection_removed')
    return 'agents.form.resourceStates.ask.connectAgain';
  return null;
}

/** Items grouped by the person who added them, in first-seen order. */
function groupByPerson(sponsors: ResourceSponsor[]) {
  const groups = new Map<string, ResourceSponsor[]>();
  for (const sponsor of sponsors) {
    const key = sponsor.label || sponsor.user_id;
    groups.set(key, [...(groups.get(key) ?? []), sponsor]);
  }
  return Array.from(groups.values());
}

/**
 * One notice for what runs on the agent with someone else's access and what
 * stopped running.
 *
 * An editor sees up front that what they attach runs with their access for
 * everyone who uses the agent, and everyone who may edit it sees who added
 * what (`resource_sponsors`). Each attached tool, source or prompt that no
 * longer runs (`resource_states`) is listed with the reason in plain words and
 * what the reader can do: sign its account in again, run it with their own
 * access, take it off, or whom to ask.
 */
export default function ResourceStatusNotice({
  agent,
  stopped,
  resolveName,
  takeovers = [],
  onTakeOver,
  onUndoTakeover,
  onRemove,
  onReconnect,
  showAttachNote: attachNoteWanted = true,
}: ResourceStatusNoticeProps) {
  const { t, i18n } = useTranslation();
  const ownerReads = isOwner(agent);
  const showAttachNote = attachNoteWanted && !ownerReads && can(agent, 'edit');
  const running = groupByPerson(
    (agent.resource_sponsors ?? []).filter((s) => s.active),
  );

  if (!showAttachNote && running.length === 0 && stopped.length === 0)
    return null;

  const listFormat = new Intl.ListFormat(intlLocale(i18n.language), {
    type: 'conjunction',
  });
  const plain = { interpolation: { escapeValue: false } };

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
      {running.length > 0 && (
        <Alert role="note">
          <UserRound />
          <AlertDescription>
            {running.map((items) => (
              <p key={items[0].key || `${items[0].type}:${items[0].id}`}>
                {t('agents.form.sponsors.addedBy', {
                  ...plain,
                  person: items[0].label || items[0].user_id,
                  names: listFormat.format(items.map(resolveName)),
                })}
              </p>
            ))}
          </AlertDescription>
        </Alert>
      )}
      {stopped.length > 0 && (
        <Alert variant="warning">
          <TriangleAlert />
          <AlertTitle>{t('agents.form.resourceStates.title')}</AlertTitle>
          <AlertDescription>
            <ul className="flex flex-col gap-3">
              {stopped.map((item) => {
                const name = resolveName(item);
                const service =
                  item.connection?.name ||
                  t('agents.form.resourceStates.serviceFallback');
                const ask = askKey(item);
                const pending = takeovers.includes(item.key);
                return (
                  <li key={item.key} className="flex flex-col gap-1.5">
                    <p>
                      {t(reasonKey(item.reason, ownerReads), {
                        ...plain,
                        name,
                        service,
                        person: item.sponsor?.label || item.sponsor?.user_id,
                      })}
                      {ask
                        ? ` ${t(ask, { ...plain, person: item.contact?.label })}`
                        : ''}
                      {item.type === 'prompt'
                        ? ` ${t('agents.form.resourceStates.promptFallback')}`
                        : ''}
                    </p>
                    {pending ? (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span>
                          {t('agents.form.sponsors.takeOverPending', {
                            ...plain,
                            name,
                          })}
                        </span>
                        <Button
                          type="button"
                          variant="link"
                          size="inline"
                          onClick={() => onUndoTakeover?.(item.key)}
                        >
                          {t('agents.form.sponsors.undoTakeOver')}
                        </Button>
                      </div>
                    ) : (
                      <div className="flex flex-wrap gap-2">
                        {item.can_reconnect && onReconnect && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            shape="pill"
                            aria-label={t(
                              'agents.form.resourceStates.reconnectLabel',
                              { ...plain, name },
                            )}
                            onClick={() => onReconnect(item)}
                          >
                            {t('settings.connectors.status.reconnect')}
                          </Button>
                        )}
                        {item.can_confirm && onTakeOver && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            shape="pill"
                            onClick={() => onTakeOver(item)}
                          >
                            {t('agents.form.sponsors.takeOver', {
                              ...plain,
                              name,
                            })}
                          </Button>
                        )}
                        {onRemove && (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            shape="pill"
                            aria-label={t(
                              'agents.form.resourceStates.removeLabel',
                              { ...plain, name },
                            )}
                            onClick={() => onRemove(item)}
                          >
                            {t('agents.form.resourceStates.remove')}
                          </Button>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
