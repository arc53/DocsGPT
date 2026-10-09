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

/**
 * Whether the link has a secret to reveal or show: a Stripe or Slack link
 * has none until the owner pastes it in.
 */
export const secretExists = (controls: {
  signature: string;
  hasSecret?: boolean;
  saved: boolean;
}): boolean =>
  controls.hasSecret === true ||
  controls.saved ||
  (!SENDER_SECRET_SCHEMES.has(controls.signature) &&
    controls.hasSecret !== false);

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
      {secretExists(controls) && (
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
      )}
    </>
  );
}

/**
 * The revealed secret, the form that sets one, and what went wrong.
 *
 * @param place - Where it shows: the chat's link card (which has the example
 *   command) or the Monitors page (which doesn't).
 */
export function SecretPanel({
  controls,
  place = 'chat',
}: {
  controls: SecretControlsState;
  place?: 'chat' | 'settings';
}) {
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
          className="flex w-full min-w-0 flex-col gap-2 sm:flex-row sm:items-center"
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
            className="w-full min-w-0 sm:flex-1"
            value={controls.draft}
            placeholder={t('monitors.linkCard.secretPlaceholder')}
            aria-label={t('monitors.linkCard.secretPlaceholder')}
            onChange={(e) => controls.setDraft(e.target.value)}
          />
          <div className="flex shrink-0 items-center gap-2">
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
          </div>
        </form>
      )}
      {controls.saved && !editing && (
        <p className="text-muted-foreground text-xs" role="status">
          {t('monitors.linkCard.secretSaved')}
        </p>
      )}
      {secret && (
        <>
          <div className="flex w-full min-w-0 items-start gap-1">
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
          <p
            className="text-muted-foreground text-xs"
            data-testid="monitor-secret-note"
          >
            {place === 'settings'
              ? t('monitors.linkCard.secretNoteSettings')
              : t('monitors.linkCard.secretNote')}
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
      exposed={Boolean(link.secret_exposed)}
    />
  );
}

function LinkSecretControls({
  monitorId,
  signature,
  hasSecret,
  exposed,
}: {
  monitorId: string;
  signature: string;
  hasSecret?: boolean;
  exposed: boolean;
}) {
  const controls = useSecretControls(monitorId, signature, hasSecret);
  return (
    <div className="mt-1 flex w-full min-w-0 flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <SecretActions controls={controls} />
        {secretExists(controls) && (
          <ExposureToggle monitorId={monitorId} initial={exposed} />
        )}
      </div>
      <SecretPanel controls={controls} place="settings" />
    </div>
  );
}

/**
 * Show (or stop showing) the raw secret to the assistant: the owner's choice
 * only, behind a warning. The assistant never gets the value otherwise.
 */
function ExposureToggle({
  monitorId,
  initial,
}: {
  monitorId: string;
  initial: boolean;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [exposed, setExposed] = useState(initial);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const change = async (next: boolean) => {
    setBusy(true);
    setFailed(false);
    const ok = await monitorsService.setExposure(monitorId, next, token);
    setBusy(false);
    setConfirming(false);
    if (ok) setExposed(next);
    else setFailed(true);
  };

  return (
    <>
      {exposed ? (
        <Button
          type="button"
          variant="outline"
          size="xs"
          shape="pill"
          disabled={busy}
          onClick={() => void change(false)}
        >
          {t('monitors.linkCard.unexposeSecret')}
        </Button>
      ) : (
        <Button
          type="button"
          variant="ghost"
          size="xs"
          shape="pill"
          disabled={busy || confirming}
          onClick={() => setConfirming(true)}
        >
          {t('monitors.linkCard.exposeSecret')}
        </Button>
      )}
      {exposed && (
        <p
          className="text-muted-foreground basis-full text-xs"
          data-testid="monitor-secret-exposed"
        >
          {t('monitors.linkCard.exposedNote')}
        </p>
      )}
      {confirming && (
        <div
          className="flex basis-full flex-col gap-2"
          data-testid="monitor-expose-confirm"
        >
          <p className="text-destructive text-xs" role="alert">
            {t('monitors.linkCard.exposeWarning')}
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="destructive"
              size="xs"
              shape="pill"
              disabled={busy}
              onClick={() => void change(true)}
            >
              {t('monitors.linkCard.exposeConfirm')}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="xs"
              shape="pill"
              onClick={() => setConfirming(false)}
            >
              {t('monitors.linkCard.cancelSecret')}
            </Button>
          </div>
        </div>
      )}
      {failed && (
        <p className="text-destructive basis-full text-xs" role="alert">
          {t('monitors.linkCard.exposeFailed')}
        </p>
      )}
    </>
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
