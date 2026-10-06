import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import monitorsService from '../api/services/monitorsService';
import CopyButton from '../components/CopyButton';
import { Button } from '../components/ui/button';
import { CodeBlock } from '../components/ui/code-block';
import { Input } from '../components/ui/input';
import { selectToken } from '../preferences/preferenceSlice';
import type { Monitor } from './types';

/** Schemes whose signing secret the sender creates: the owner pastes it in. */
export const SENDER_SECRET_SCHEMES: ReadonlySet<string> = new Set([
  'stripe',
  'slack',
]);

/** Whether a webhook link with this signature scheme has a secret at all. */
export const isSigned = (signature: string | null | undefined): boolean =>
  Boolean(signature) && signature !== 'none';

type Problem =
  'failed' | 'limited' | 'missing' | 'saveFailed' | 'saveInvalid' | null;

const PROBLEM_KEY: Record<Exclude<Problem, null>, string> = {
  failed: 'monitors.linkCard.revealFailed',
  limited: 'monitors.linkCard.revealLimited',
  missing: 'monitors.linkCard.revealMissing',
  saveFailed: 'monitors.linkCard.setSecretFailed',
  saveInvalid: 'monitors.linkCard.setSecretInvalid',
};

/**
 * Reveal, hide and set a webhook link's signing secret. The value lives in
 * this hook's state only: never in the store, never logged.
 */
export function useSecretControls(
  monitorId: string,
  signature: string,
  hasSecret?: boolean,
) {
  const token = useSelector(selectToken);
  const [secret, setSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saved, setSaved] = useState(false);
  const [invalidReason, setInvalidReason] = useState('');

  const reveal = async () => {
    setBusy(true);
    setProblem(null);
    const result = await monitorsService.revealSecret(monitorId, token);
    setBusy(false);
    if (result.state === 'ok') setSecret(result.secret);
    else setProblem(result.state === 'error' ? 'failed' : result.state);
  };

  const toggleReveal = () => {
    if (secret) setSecret(null);
    else void reveal();
  };

  const startEditing = () => {
    setEditing(true);
    setSaved(false);
    setProblem(null);
  };

  const cancelEditing = () => {
    setEditing(false);
    setDraft('');
    setProblem(null);
  };

  const save = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    setProblem(null);
    const result = await monitorsService.setSecret(
      monitorId,
      draft.trim(),
      token,
    );
    setBusy(false);
    if (result.state === 'saved') {
      setEditing(false);
      setDraft('');
      setSecret(null);
      setSaved(true);
    } else if (result.state === 'invalid') {
      setInvalidReason(result.message);
      setProblem('saveInvalid');
    } else if (result.state === 'limited') {
      setProblem('limited');
    } else if (result.state === 'missing') {
      setProblem('missing');
    } else {
      setProblem('saveFailed');
    }
  };

  return {
    signature,
    hasSecret,
    secret,
    busy,
    problem,
    invalidReason,
    editing,
    draft,
    saved,
    setDraft,
    toggleReveal,
    startEditing,
    cancelEditing,
    save,
  };
}

export type SecretControlsState = ReturnType<typeof useSecretControls>;

/** The Reveal / Hide and Set signing secret buttons. */
export function SecretActions({ controls }: { controls: SecretControlsState }) {
  const { t } = useTranslation();
  const { secret, busy, editing, signature } = controls;
  const senderCreated = SENDER_SECRET_SCHEMES.has(signature);
  return (
    <>
      {senderCreated && !editing && (
        <Button
          type="button"
          variant="outline"
          size="xs"
          shape="pill"
          disabled={busy}
          onClick={controls.startEditing}
        >
          {t('monitors.linkCard.setSecret')}
        </Button>
      )}
      <Button
        type="button"
        variant="outline"
        size="xs"
        shape="pill"
        disabled={busy}
        onClick={controls.toggleReveal}
      >
        {secret
          ? t('monitors.linkCard.hideSecret')
          : t('monitors.linkCard.revealSecret')}
      </Button>
    </>
  );
}

/** The revealed secret, the form that sets one, and what went wrong. */
export function SecretPanel({ controls }: { controls: SecretControlsState }) {
  const { t } = useTranslation();
  const { secret, editing, problem, signature } = controls;
  const senderCreated = SENDER_SECRET_SCHEMES.has(signature);
  return (
    <>
      {senderCreated &&
        controls.hasSecret !== true &&
        !secret &&
        !editing &&
        !controls.saved && (
          <p className="text-muted-foreground text-xs">
            {t('monitors.linkCard.senderSecretNote', {
              sender: signature === 'stripe' ? 'Stripe' : 'Slack',
              interpolation: { escapeValue: false },
            })}
          </p>
        )}
      {editing && (
        <form
          className="flex min-w-0 items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void controls.save();
          }}
        >
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            size="sm"
            variant="filled"
            className="min-w-0 flex-1"
            value={controls.draft}
            placeholder={t('monitors.linkCard.secretPlaceholder')}
            aria-label={t('monitors.linkCard.secretPlaceholder')}
            onChange={(e) => controls.setDraft(e.target.value)}
          />
          <Button
            type="submit"
            size="xs"
            shape="pill"
            disabled={controls.busy || !controls.draft.trim()}
          >
            {t('monitors.linkCard.saveSecret')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            shape="pill"
            onClick={controls.cancelEditing}
          >
            {t('monitors.linkCard.cancelSecret')}
          </Button>
        </form>
      )}
      {controls.saved && !editing && (
        <p className="text-muted-foreground text-xs" role="status">
          {t('monitors.linkCard.secretSaved')}
        </p>
      )}
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
          {t(PROBLEM_KEY[problem], {
            reason: controls.invalidReason,
            interpolation: { escapeValue: false },
          })}
        </p>
      )}
    </>
  );
}

/**
 * A monitor's signing-secret controls on the Monitors page: Reveal / Hide
 * and, for Stripe and Slack, Set signing secret, while its webhook link is
 * live and signed. Nothing for any other monitor.
 */
export function MonitorSecretControls({ monitor }: { monitor: Monitor }) {
  const link = liveSignedLink(monitor);
  if (!link) return null;
  return (
    <LinkSecretControls
      monitorId={monitor.monitor_id}
      signature={link.signature as string}
      hasSecret={link.has_secret}
    />
  );
}

function LinkSecretControls({
  monitorId,
  signature,
  hasSecret,
}: {
  monitorId: string;
  signature: string;
  hasSecret?: boolean;
}) {
  const controls = useSecretControls(monitorId, signature, hasSecret);
  return (
    <div className="mt-1 flex min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <SecretActions controls={controls} />
      </div>
      <SecretPanel controls={controls} />
    </div>
  );
}

/** A live monitor's live, signed webhook link, or undefined. */
export function liveSignedLink(monitor: Monitor) {
  if (monitor.status !== 'active' && monitor.status !== 'paused') return;
  return monitor.links?.find(
    (link) =>
      link.kind === 'webhook' &&
      (link.state ?? 'live') === 'live' &&
      isSigned(link.signature),
  );
}
