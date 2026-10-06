import { Webhook } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import monitorsService from '../api/services/monitorsService';
import CopyButton from '../components/CopyButton';
import { Button } from '../components/ui/button';
import { CodeBlock } from '../components/ui/code-block';
import ToolCallCard from '../conversation/ToolCallCard';
import { selectToken } from '../preferences/preferenceSlice';

/** What the card needs from a `monitor_create` result that made a webhook link. */
export type MonitorLink = {
  monitorId: string;
  url: string;
  /** `none`, `github`, `hmac_sha256` or `standard_webhooks`. */
  signature: string;
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
  let monitorId: unknown;
  let url: unknown;
  let signature: unknown;
  if (result && typeof result === 'object') {
    ({
      monitor_id: monitorId,
      url,
      signature,
    } = result as Record<string, unknown>);
  } else if (typeof result === 'string') {
    try {
      ({ monitor_id: monitorId, url, signature } = JSON.parse(result));
    } catch {
      monitorId = field(result, 'monitor_id');
      url = field(result, 'url');
      signature = field(result, 'signature');
    }
  }
  if (typeof monitorId !== 'string' || typeof url !== 'string') return null;
  if (!url.includes('/api/triggers/')) return null;
  return {
    monitorId,
    url,
    signature: typeof signature === 'string' ? signature : 'none',
  };
}

type RevealState = 'idle' | 'loading' | 'failed' | 'limited' | 'missing';

const PROBLEM_KEY: Partial<Record<RevealState, string>> = {
  failed: 'monitors.linkCard.revealFailed',
  limited: 'monitors.linkCard.revealLimited',
  missing: 'monitors.linkCard.revealMissing',
};

/**
 * A webhook link the assistant made, in the chat: the URL to copy and, for a
 * signed link, a Reveal secret button. The assistant only ever sees a
 * placeholder for the secret; the owner fetches it here, and it lives in this
 * card's state only (never in the store, never logged).
 */
export default function MonitorLinkCard({ link }: { link: MonitorLink }) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [secret, setSecret] = useState<string | null>(null);
  const [state, setState] = useState<RevealState>('idle');
  const signed = Boolean(link.signature) && link.signature !== 'none';

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
        icon={<Webhook className="text-muted-foreground size-4" aria-hidden />}
        title={t('monitors.linkCard.title')}
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
