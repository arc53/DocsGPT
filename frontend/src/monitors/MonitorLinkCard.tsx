import { ShieldCheck, Webhook } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import monitorsService from '../api/services/monitorsService';
import CopyButton from '../components/CopyButton';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { CodeBlock } from '../components/ui/code-block';
import ToolCallCard from '../conversation/ToolCallCard';
import { selectToken } from '../preferences/preferenceSlice';
import { formatDeadline } from '../utils/dateTimeUtils';
import { selectMonitor, type WithMonitors } from './monitorsSlice';
import type { Monitor } from './types';

/** What the card needs from a `monitor_create` result that made a webhook or approval link. */
export type MonitorLink = {
  kind: 'webhook' | 'approval';
  monitorId: string;
  url: string;
  /** `none`, `github`, `hmac_sha256` or `standard_webhooks` (a webhook link). */
  signature: string;
  /** The question an approval link asks. */
  question?: string;
  expiresAt?: string;
};

const field = (text: string, name: string): string | null => {
  const match = new RegExp(`"${name}"\\s*:\\s*"([^"]*)"`).exec(text);
  return match ? match[1] : null;
};

/**
 * The webhook link in a `monitor_create` result, or null for any other
 * result. The stored result can be cut short (long results are truncated),
 * so a result that is no longer valid JSON is read field by field.
 */
export function parseMonitorLink(result: unknown): MonitorLink | null {
  const names = ['monitor_id', 'url', 'signature', 'question', 'expires_at'];
  let data: Record<string, unknown> = {};
  if (result && typeof result === 'object') {
    data = result as Record<string, unknown>;
  } else if (typeof result === 'string') {
    try {
      const parsed = JSON.parse(result);
      if (parsed && typeof parsed === 'object') data = parsed;
    } catch {
      for (const name of names) data[name] = field(result, name);
    }
  }
  const text = (name: string): string | undefined =>
    typeof data[name] === 'string' ? (data[name] as string) : undefined;
  const monitorId = text('monitor_id');
  const url = text('url');
  if (!monitorId || !url) return null;
  const kind = url.includes('/api/triggers/')
    ? 'webhook'
    : /\/approve\/apv_/.test(url)
      ? 'approval'
      : null;
  if (!kind) return null;
  const link: MonitorLink = {
    kind,
    monitorId,
    url,
    signature: text('signature') ?? 'none',
  };
  const question = text('question');
  const expiresAt = text('expires_at');
  if (question) link.question = question;
  if (expiresAt) link.expiresAt = expiresAt;
  return link;
}

type LinkState = 'active' | 'pending' | 'decided' | 'ended';

/**
 * Where the link stands, from its monitor as the store knows it (kept live by
 * `monitor.updated`). A monitor the store hasn't loaded counts as live.
 */
export function linkState(
  kind: MonitorLink['kind'],
  monitor: Monitor | undefined,
  now: number = Date.now(),
  expiresAt?: string,
): LinkState {
  const live = kind === 'approval' ? 'pending' : 'active';
  if (!monitor) {
    const end = expiresAt ? Date.parse(expiresAt) : NaN;
    return Number.isFinite(end) && end <= now ? 'ended' : live;
  }
  if (monitor.status === 'active' || monitor.status === 'paused') return live;
  if (kind === 'approval' && monitor.paused_reason === 'decided')
    return 'decided';
  return 'ended';
}

const STATE_BADGE: Record<LinkState, 'info' | 'success' | 'neutral'> = {
  active: 'info',
  pending: 'info',
  decided: 'success',
  ended: 'neutral',
};

type RevealState = 'idle' | 'loading' | 'failed' | 'limited' | 'missing';

const PROBLEM_KEY: Partial<Record<RevealState, string>> = {
  failed: 'monitors.linkCard.revealFailed',
  limited: 'monitors.linkCard.revealLimited',
  missing: 'monitors.linkCard.revealMissing',
};

/**
 * A webhook or approval link the assistant made, in the chat: the URL to
 * copy, its expiry and where it stands (waiting, decided, ended). A signed
 * webhook link also has a Reveal secret button while the link is live. The
 * assistant only ever sees a placeholder for the secret; the owner fetches it
 * here, and it lives in this card's state only (never in the store, never
 * logged).
 */
export default function MonitorLinkCard({ link }: { link: MonitorLink }) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const monitor = useSelector((state: WithMonitors) =>
    selectMonitor(state, link.monitorId),
  );
  const [secret, setSecret] = useState<string | null>(null);
  const [state, setState] = useState<RevealState>('idle');
  const status = linkState(link.kind, monitor, Date.now(), link.expiresAt);
  const ended = status === 'ended' || status === 'decided';
  const signed =
    link.kind === 'webhook' &&
    Boolean(link.signature) &&
    link.signature !== 'none' &&
    !ended;
  const expiresAt = monitor?.expires_at ?? link.expiresAt;

  const reveal = async () => {
    setState('loading');
    const result = await monitorsService.revealSecret(link.monitorId, token);
    if (result.state === 'ok') {
      setSecret(result.secret);
      setState('idle');
    } else {
      setState(result.state === 'error' ? 'failed' : result.state);
    }
  };

  const problem = PROBLEM_KEY[state];

  return (
    <div className="my-2 mr-5 ml-6" data-testid="monitor-link-card">
      <ToolCallCard
        icon={
          link.kind === 'approval' ? (
            <ShieldCheck className="text-muted-foreground size-4" aria-hidden />
          ) : (
            <Webhook className="text-muted-foreground size-4" aria-hidden />
          )
        }
        title={t(
          link.kind === 'approval'
            ? 'monitors.linkCard.approvalTitle'
            : 'monitors.linkCard.title',
        )}
        actions={
          signed ? (
            <Button
              type="button"
              variant="outline"
              size="xs"
              shape="pill"
              disabled={state === 'loading'}
              onClick={() => {
                if (secret) setSecret(null);
                else void reveal();
              }}
            >
              {secret
                ? t('monitors.linkCard.hideSecret')
                : t('monitors.linkCard.revealSecret')}
            </Button>
          ) : null
        }
      >
        <div className="flex flex-col gap-2">
          {link.question && (
            <p className="text-foreground text-sm">{link.question}</p>
          )}
          <div className="flex min-w-0 items-start gap-1">
            <CodeBlock
              surface="subtle"
              wrap="anywhere"
              className="min-w-0 flex-1"
            >
              {link.url}
            </CodeBlock>
            <CopyButton
              textToCopy={link.url}
              copyLabel={t('monitors.linkCard.copyUrl')}
            />
          </div>
          {secret && (
            <>
              <div className="flex min-w-0 items-start gap-1">
                <CodeBlock
                  surface="subtle"
                  wrap="anywhere"
                  className="min-w-0 flex-1"
                >
                  <span data-testid="monitor-link-secret">{secret}</span>
                </CodeBlock>
                <CopyButton
                  textToCopy={secret}
                  copyLabel={t('monitors.linkCard.copySecret')}
                />
              </div>
              <p className="text-muted-foreground text-xs">
                {t('monitors.linkCard.secretNote')}
              </p>
            </>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge
              variant={STATE_BADGE[status]}
              data-testid="monitor-link-state"
            >
              {t(`monitors.linkCard.state.${status}`)}
            </Badge>
            {expiresAt && !ended && (
              <span className="text-muted-foreground">
                {t('monitors.linkCard.expires', {
                  date: formatDeadline(expiresAt),
                  interpolation: { escapeValue: false },
                })}
              </span>
            )}
          </div>
          {problem && (
            <p className="text-destructive text-xs" role="alert">
              {t(problem)}
            </p>
          )}
        </div>
      </ToolCallCard>
    </div>
  );
}
