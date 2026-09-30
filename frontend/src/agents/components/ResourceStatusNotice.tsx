import type { TFunction } from 'i18next';
import { TriangleAlert, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { IconButton } from '@/components/ui/icon-button';
import { cn } from '@/lib/utils';

import { isOwner } from '../../utils/accessUtils';
import { isReader, personLabel } from '../../utils/personLabel';
import type { Agent, ResourceState } from '../types';

/** What the notice needs to name an item. */
export type NamedResource = Pick<ResourceState, 'type' | 'id' | 'name'>;

type ResourceStatusNoticeProps = {
  /** The agent the page edits: the reader's access. */
  agent: Agent;
  /** Stopped items still attached in the form (`resource_states`). */
  stopped: ResourceState[];
  /** Display name of a tool, source or prompt. */
  resolveName: (item: NamedResource) => string;
  /** The reader's user id, to say "you" where a reason is about them. */
  readerId?: string;
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
  /**
   * Floating over a canvas: a close button inside the warning, and the list
   * in its own scroller so a long one stays on screen.
   */
  onClose?: () => void;
};

/**
 * Why an item stopped, as the last part of its message key: the same under
 * `agents.form.resourceStates.reason` (a sentence) and
 * `settings.teams.share.uses.reasonShort` (a list row's meta).
 *
 * Args:
 *   item: The stopped item.
 *   options: `ownerReads` when the agent's owner reads it; `readerId` to
 *     recognise the reader as the sponsor; `noService` when the message
 *     shouldn't name the service (none known, or the item is named after it).
 *
 * Returns:
 *   The key suffix: an unnamed sponsor is `…Other`, the reader `…You`.
 */
export function stoppedReason(
  item: Pick<ResourceState, 'reason' | 'sponsor'>,
  {
    ownerReads,
    readerId,
    noService = false,
  }: { ownerReads: boolean; readerId?: string; noService?: boolean },
): string {
  const who = isReader(item.sponsor, readerId)
    ? 'You'
    : item.sponsor?.user_id
      ? ''
      : 'Other';
  const service = noService ? 'NoService' : '';
  switch (item.reason) {
    case 'deleted':
      return 'deleted';
    case 'owner_lost_access':
      return ownerReads ? 'ownerLostAccessYou' : 'ownerLostAccess';
    case 'sponsor_cannot_edit_agent':
      // The reader can edit the agent, so they are never this sponsor.
      return `sponsorCannotEditAgent${who === 'You' ? '' : who}`;
    case 'sponsor_cannot_edit_resource':
      return `sponsorCannotEditItem${who}`;
    case 'connection_needs_reconnect':
      return `connectionNeedsReconnect${service}`;
    case 'connection_removed':
      return `connectionRemoved${service}`;
    case 'connector_disabled':
      return `connectorDisabled${service}`;
    default:
      return 'unknown';
  }
}

/** Whether a message about `name` should leave its service out. */
export function omitService(name: string, service?: string | null): boolean {
  const trimmed = service?.trim();
  return !trimmed || trimmed.toLowerCase() === name.trim().toLowerCase();
}

/** A name for an item the reader may not see: its kind and a short id. */
export function unnamedResourceLabel(
  t: TFunction,
  item: Pick<NamedResource, 'type' | 'id'>,
): string {
  return t(`agents.form.resourceStates.unnamed.${item.type}`, {
    id: item.id.slice(0, 8),
  });
}

/**
 * Whom to ask, as the key that says so; null when the reader can act. The
 * person is named when the read names them (`contact`), else only as the
 * item's owner.
 */
function askKey(item: ResourceState): string | null {
  if (item.reason === 'connector_disabled')
    return 'agents.form.resourceStates.ask.admin';
  const suffix = item.contact
    ? ''
    : item.contact_role === 'resource_owner'
      ? 'Owner'
      : null;
  if (suffix === null) return null;
  if (item.reason === 'owner_lost_access')
    return `agents.form.resourceStates.ask.shareAgain${suffix}`;
  if (item.reason === 'connection_needs_reconnect')
    return `agents.form.resourceStates.ask.signInAgain${suffix}`;
  if (item.reason === 'connection_removed')
    return `agents.form.resourceStates.ask.connectAgain${suffix}`;
  return null;
}

/**
 * The warning for attached tools, sources and prompts that stopped running
 * (`resource_states`): each with the reason in plain words and what the
 * reader can do — sign its account in again, run it with their own access,
 * take it off, or whom to ask. Who added what is in the pickers, and the
 * sponsor confirmation asks before anything runs with the reader's access,
 * so nothing shows while everything runs.
 */
export default function ResourceStatusNotice({
  agent,
  stopped,
  resolveName,
  readerId,
  takeovers = [],
  onTakeOver,
  onUndoTakeover,
  onRemove,
  onReconnect,
  onClose,
}: ResourceStatusNoticeProps) {
  const { t } = useTranslation();
  const ownerReads = isOwner(agent);

  if (stopped.length === 0) return null;

  const plain = { interpolation: { escapeValue: false } };

  const list = (
    <ul className="flex flex-col gap-3">
      {stopped.map((item) => {
        const name = resolveName(item);
        const service = item.connection?.name ?? '';
        const ask = askKey(item);
        const pending = takeovers.includes(item.key);
        const reason = stoppedReason(item, {
          ownerReads,
          readerId,
          noService: omitService(name, service),
        });
        return (
          <li key={item.key} className="flex flex-col gap-1.5">
            <p>
              {t(`agents.form.resourceStates.reason.${reason}`, {
                ...plain,
                name,
                service,
                person: personLabel(item.sponsor),
              })}
              {ask
                ? ` ${t(ask, { ...plain, person: personLabel(item.contact) })}`
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
                  size="text"
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
                    aria-label={t('agents.form.resourceStates.reconnectLabel', {
                      ...plain,
                      name,
                    })}
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
                    aria-label={t('agents.form.sponsors.takeOverLabel', {
                      ...plain,
                      name,
                    })}
                    onClick={() => onTakeOver(item)}
                  >
                    {t('agents.form.sponsors.takeOver')}
                  </Button>
                )}
                {onRemove && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    shape="pill"
                    aria-label={t('agents.form.resourceStates.removeLabel', {
                      ...plain,
                      name,
                    })}
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
  );

  return (
    <Alert
      variant="warning"
      // eslint-disable-next-line shadcn/no-restyle -- floating over the workflow canvas, the close button sits in the top-right corner, so the title pads clear of it (as the publish errors do)
      className={cn('sm:col-span-2', onClose && 'pr-10')}
    >
      <TriangleAlert />
      <AlertTitle>{t('agents.form.resourceStates.title')}</AlertTitle>
      <AlertDescription>
        {onClose ? (
          <div className="scrollbar-overlay max-h-[45svh] overflow-y-auto">
            {list}
          </div>
        ) : (
          list
        )}
      </AlertDescription>
      {onClose && (
        <div className="absolute top-2.5 right-2.5">
          <IconButton
            variant="ghost"
            size="icon-xs"
            onClick={onClose}
            label={t('agents.close')}
            icon={X}
          />
        </div>
      )}
    </Alert>
  );
}
