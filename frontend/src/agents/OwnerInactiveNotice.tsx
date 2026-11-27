import type { TFunction } from 'i18next';
import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
} from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { pauseReasonText } from '../payer/pauseReason';
import {
  isPausedFor,
  OUTSIDE_ACCESS_KINDS,
  type OutsideAccess,
} from '../payer/types';
import { isOwner } from '../utils/accessUtils';
import { readerIdFromToken } from '../utils/personLabel';
import type { Agent } from './types';

/** The agent whose pages are open, as the route guard read it. */
type NoticeAgent = Agent;

/**
 * The agent whose pages are open, as the route guard read it. Its pages'
 * toolbars read notices about the agent from here.
 */
export const AgentNoticeContext = createContext<NoticeAgent | null>(null);

/** Whether any way in from outside (key, public link, webhook) is on. */
export const outsideAccessOn = (access: OutsideAccess | null | undefined) =>
  !!access && OUTSIDE_ACCESS_KINDS.some((kind) => access[kind]);

type ReaderState = {
  token?: string | null;
  workspace?: { workspaces?: { id: string; name?: string | null }[] };
};

/**
 * The reader's id and the name of the agent's team, from the store. Only
 * the paused notices call it, so a page with nothing paused needs no store.
 */
function useReader(agent: Pick<Agent, 'workspace'> | null | undefined) {
  const token = useSelector(
    (state: { preference?: ReaderState }) => state.preference?.token ?? null,
  );
  const teamId =
    agent?.workspace?.kind === 'team' ? agent.workspace.team_id : null;
  const teamName = useSelector(
    (state: { workspace?: ReaderState['workspace'] }) =>
      (teamId &&
        state.workspace?.workspaces?.find((row) => row.id === teamId)?.name) ||
      null,
  );
  return { token, me: readerIdFromToken(token), teamName };
}

/**
 * Why an agent's outside access is paused, in one sentence ("Dana is out of
 * allowance until 1 Dec."), or an empty string when it isn't or the reason
 * is not one the app knows.
 *
 * Args:
 *   t: The translate function.
 *   agent: The agent; a personal agent's owner is its payer.
 *   access: Its `outside_access`.
 *   reader: The reader's id, the team's name and the UI language.
 */
export function outsidePauseReason(
  t: TFunction,
  agent: Pick<Agent, 'workspace' | 'access' | 'allowed_actions'>,
  access: OutsideAccess | null | undefined,
  {
    me,
    teamName,
    language,
  }: { me?: string | null; teamName?: string | null; language?: string },
): string {
  const paused = access?.paused_for;
  if (!isPausedFor(paused)) return '';
  const payer = access?.paid_by ?? null;
  // A personal agent names no payer: its owner pays.
  const you = payer
    ? !!me && payer.user_id === me
    : agent.workspace?.kind !== 'team' && isOwner(agent);
  return pauseReasonText(t, paused, payer?.label, teamName, {
    you,
    language,
  });
}

// What the notices read of an agent's outside access when the opened agent
// came from the list (which doesn't carry it), or changed on the page since
// (a Take over in Access details). Kept per agent id for this session.
const FRESH_MS = 30_000;
const remembered = new Map<
  string,
  { at: number; access: OutsideAccess | null }
>();
const listeners = new Set<() => void>();
// When the notices first saw each agent record's `outside_access`. What the
// page learned later beats a record seen before it, however long ago: the
// page keeps the record it opened with, which a Take over made stale.
const recordSeenAt = new WeakMap<OutsideAccess, number>();

const seenAt = (record: OutsideAccess): number => {
  let at = recordSeenAt.get(record);
  if (at === undefined) {
    at = Date.now();
    recordSeenAt.set(record, at);
  }
  return at;
};

/**
 * Tells the agent's notices what its outside access is now: after a Take
 * over or a change in Access details, so the page's notice follows at once.
 *
 * Args:
 *   agentId: The agent's id.
 *   access: The `outside_access` the server answered with; null for none.
 */
export function rememberOutsideAccess(
  agentId: string,
  access: OutsideAccess | null,
): void {
  remembered.set(agentId, { at: Date.now(), access });
  listeners.forEach((listener) => listener());
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/**
 * The opened agent's outside access: what it carries, unless the page
 * learned something since that record was first seen, and whether it still
 * has to be read (an agent from the list, for a reader who manages its
 * access).
 */
function useOutsideAccess(agent: NoticeAgent | null | undefined): {
  access: OutsideAccess | null;
  needsRead: boolean;
} {
  const id = agent?.id ?? '';
  const entry = useSyncExternalStore(
    subscribe,
    () => remembered.get(id),
    () => remembered.get(id),
  );
  const own = agent?.outside_access;
  // Noted on every render, so a record is dated before anything is learned.
  const ownSeenAt = own ? seenAt(own) : null;
  const fresh = !!entry && Date.now() - entry.at < FRESH_MS;
  const newer =
    !!entry &&
    (own === undefined || (ownSeenAt === null ? fresh : entry.at >= ownSeenAt));
  const access = newer ? entry.access : own;
  const needsRead =
    !!id &&
    own === undefined &&
    !fresh &&
    agent?.status !== 'draft' &&
    // The server's own word only: a record without it is not read.
    !!agent?.allowed_actions?.includes('manage_access_details');
  return { access: access ?? null, needsRead };
}

/** Reads the agent once for its outside access, which the list leaves out. */
function ReadOutsideAccess({ agentId }: { agentId: string }) {
  const token = useSelector(
    (state: { preference?: ReaderState }) => state.preference?.token ?? null,
  );
  useEffect(() => {
    let cancelled = false;
    userService
      .getAgent(agentId, token)
      .then(async (response: Response) => {
        if (!response.ok) return;
        const body = (await response.json()) as Partial<Agent>;
        if (!cancelled)
          rememberOutsideAccess(agentId, body.outside_access ?? null);
      })
      .catch(() => {
        // The notice is extra: without it the page says nothing.
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, token]);
  return null;
}

/** The paused-for-its-payer sentence: "Outside access is paused. Dana …". */
function usePausedSentence(
  agent: NoticeAgent,
  access: OutsideAccess | null,
): string {
  const { t, i18n } = useTranslation();
  const { me, teamName } = useReader(agent);
  const reason = outsidePauseReason(t, agent, access, {
    me,
    teamName,
    language: i18n?.language,
  });
  return reason
    ? t('payer.access.notice', {
        reason,
        interpolation: { escapeValue: false },
      })
    : t('payer.access.noticeUnknown');
}

/** Whether the agent's outside access is paused for its owner's account. */
const ownerOff = (agent: NoticeAgent, access: OutsideAccess | null) =>
  !!agent.owner_inactive || access?.paused_for?.reason === 'owner_inactive';

/** Whether it is paused for its payer, with something on to pause. */
const payerPaused = (access: OutsideAccess | null) =>
  !!access?.paused_for && outsideAccessOn(access);

function PayerPausedNotice({
  agent,
  access,
  className,
}: {
  agent: NoticeAgent;
  access: OutsideAccess | null;
  className?: string;
}) {
  const sentence = usePausedSentence(agent, access);
  return (
    <Alert variant="warning" role="note" className={className}>
      <AlertDescription>
        <p>{sentence}</p>
      </AlertDescription>
    </Alert>
  );
}

/**
 * Why the agent's outside access (key, public link, webhook) is paused:
 * its owner's account is deactivated, its payer left the team or lost the
 * role, nobody pays, or the payer is out of allowance until a date. An
 * agent from the list doesn't carry who pays, so for a reader who manages
 * its access the notice reads the agent once.
 *
 * Args:
 *   agent: The agent; the opened one when left out.
 *   className: Placement.
 */
export function OutsideAccessNotice({
  agent,
  className,
}: {
  agent?: NoticeAgent | null;
  className?: string;
}) {
  const { t } = useTranslation();
  const opened = useContext(AgentNoticeContext);
  const target = agent ?? opened;
  const { access, needsRead } = useOutsideAccess(target);
  if (!target) return null;
  const read =
    needsRead && target.id ? <ReadOutsideAccess agentId={target.id} /> : null;
  if (ownerOff(target, access))
    return (
      <>
        {read}
        <Alert variant="warning" role="note" className={className}>
          <AlertDescription>
            <p>{t('workspace.notices.ownerInactive')}</p>
          </AlertDescription>
        </Alert>
      </>
    );
  return (
    <>
      {read}
      {payerPaused(access) ? (
        <PayerPausedNotice
          agent={target}
          access={access}
          className={className}
        />
      ) : null}
    </>
  );
}

/** The agent page's notice; its first name, kept for the pages that use it. */
export default OutsideAccessNotice;

function PayerPausedBadge({
  agent,
  access,
}: {
  agent: NoticeAgent;
  access: OutsideAccess | null;
}) {
  const { t } = useTranslation();
  return (
    <Badge variant="warning" title={usePausedSentence(agent, access)}>
      {t('workspace.notices.ownerInactiveShort')}
    </Badge>
  );
}

/** The same notice as a status Badge, for the workflow builder's one-row header. */
export function OwnerInactiveBadge() {
  const { t } = useTranslation();
  const opened = useContext(AgentNoticeContext);
  const { access, needsRead } = useOutsideAccess(opened);
  if (!opened) return null;
  const read =
    needsRead && opened.id ? <ReadOutsideAccess agentId={opened.id} /> : null;
  if (ownerOff(opened, access))
    return (
      <>
        {read}
        <Badge variant="warning" title={t('workspace.notices.ownerInactive')}>
          {t('workspace.notices.ownerInactiveShort')}
        </Badge>
      </>
    );
  return (
    <>
      {read}
      {payerPaused(access) ? (
        <PayerPausedBadge agent={opened} access={access} />
      ) : null}
    </>
  );
}
