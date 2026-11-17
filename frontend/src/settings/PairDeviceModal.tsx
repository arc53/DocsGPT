import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import devicesService, {
  ApprovalMode,
  DevicesApiError,
  PairingResponse,
} from '../api/services/devicesService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { CopyField } from '../components/ui/code-block';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';

interface Props {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  onPaired?: (deviceId: string, deviceName: string) => void;
}

type Stage = 'form' | 'waiting';

// How long the check at expiry may take before the code shows as expired.
const FINAL_CHECK_TIMEOUT_MS = 5000;

export default function PairDeviceModal({
  modalState,
  setModalState,
  onPaired,
}: Props) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [stage, setStage] = React.useState<Stage>('form');
  const [name, setName] = React.useState('');
  const [description, setDescription] = React.useState('');
  const [approvalMode, setApprovalMode] = React.useState<ApprovalMode>('ask');
  const [submitting, setSubmitting] = React.useState(false);

  const [pairing, setPairing] = React.useState<PairingResponse | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [expired, setExpired] = React.useState(false);
  // The code's lifetime is known up front, so expiry needn't wait on a poll.
  const expiresAtRef = React.useRef(0);

  const reset = React.useCallback(() => {
    setStage('form');
    setName('');
    setDescription('');
    setApprovalMode('ask');
    setSubmitting(false);
    setPairing(null);
    setError(null);
    setExpired(false);
  }, []);

  React.useEffect(() => {
    if (modalState === 'INACTIVE') {
      reset();
    }
  }, [modalState, reset]);

  const installCommand = React.useMemo(() => {
    const url = baseURL || '';
    return `docsgpt-cli host pair --url ${url}`;
  }, []);

  const handleStart = async () => {
    setError(null);
    setExpired(false);
    setSubmitting(true);
    try {
      const trimmedName = name.trim();
      const trimmedDescription = description.trim();
      const res = await devicesService.startPairing(token, {
        name: trimmedName || undefined,
        description: trimmedDescription || undefined,
        approval_mode: approvalMode,
      });
      expiresAtRef.current = Date.now() + res.expires_in * 1000;
      setPairing(res);
      setStage('waiting');
    } catch (err: unknown) {
      console.error('start pairing failed', err);
      setError(t('common.actionFailed'));
    } finally {
      setSubmitting(false);
    }
  };

  // Poll while waiting for the CLI to redeem.
  React.useEffect(() => {
    if (stage !== 'waiting' || !pairing) return;
    // Set once this code is settled or the effect is cleaned up, so a poll
    // still in flight can't act afterwards: it can't reopen a closed dialog
    // as expired (closing cancels the pairing, which then answers 404), and
    // an old code's redemption can't close the dialog for a new code.
    let stopped = false;
    const expiresAt = expiresAtRef.current;
    const pollIntervalMs = (pairing.interval > 0 ? pairing.interval : 3) * 1000;
    const requests = new AbortController();
    let finalCheckTimer: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      stopped = true;
      requests.abort();
      clearInterval(pollTimer);
      clearTimeout(expiryTimer);
      clearTimeout(finalCheckTimer);
    };
    const expire = () => {
      stop();
      setPairing(null);
      setStage('form');
      setExpired(true);
    };
    const check = async (atExpiry: boolean) => {
      try {
        const s = await devicesService.pollPairing(
          pairing.device_code,
          token,
          requests.signal,
        );
        if (stopped) return;
        // A redemption counts even past the deadline: the CLI may redeem in
        // the last seconds, and the server keeps the redeemed state after.
        if (s.status === 'redeemed') {
          stop();
          if (s.device_id && s.device_name) {
            onPaired?.(s.device_id, s.device_name);
          }
          setModalState('INACTIVE');
        } else if (
          atExpiry ||
          s.status === 'expired' ||
          s.status === 'cancelled'
        ) {
          expire();
        }
      } catch (err) {
        if (stopped) return;
        // The server drops a code once it expires or is cancelled.
        const notFound = err instanceof DevicesApiError && err.status === 404;
        if (!notFound) console.error('pairing poll failed', err);
        if (notFound || atExpiry) expire();
      }
    };
    const pollTimer = setInterval(() => {
      // Past the deadline, the check at expiry decides the outcome.
      if (Date.now() >= expiresAt) return;
      void check(false);
    }, pollIntervalMs);
    // At the deadline, check once more before showing the code as expired.
    const expiryTimer = setTimeout(
      () => {
        clearInterval(pollTimer);
        finalCheckTimer = setTimeout(expire, FINAL_CHECK_TIMEOUT_MS);
        void check(true);
      },
      Math.max(0, expiresAt - Date.now()),
    );
    return stop;
  }, [stage, pairing, token, onPaired, setModalState]);

  const close = () => {
    if (pairing && stage === 'waiting') {
      void devicesService
        .cancelPairing(pairing.device_code, token)
        .catch(() => {});
    }
    setModalState('INACTIVE');
  };

  const userCode = pairing?.user_code || '';

  const renderForm = () => (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        {t('settings.devices.pairing.formSubtitle')}
      </p>
      <Input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        label={t('settings.devices.pairing.nameLabel')}
        placeholder={t('settings.devices.pairing.namePlaceholder')}
      />
      <Input
        type="text"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        label={t('settings.devices.pairing.descriptionLabel')}
        placeholder={t('settings.devices.pairing.descriptionPlaceholder')}
      />
      <div className="flex flex-col gap-2">
        <span className="text-muted-foreground text-xs">
          {t('settings.devices.approvalMode')}
        </span>
        <Select
          value={approvalMode}
          onValueChange={(value) => setApprovalMode(value as ApprovalMode)}
        >
          <SelectTrigger className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ask">
              {t('settings.devices.approvalAsk')}
            </SelectItem>
            <SelectItem value="full">
              {t('settings.devices.approvalFull')}
            </SelectItem>
          </SelectContent>
        </Select>
        {approvalMode === 'full' && (
          <Alert variant="destructive">
            <AlertDescription>
              {t('settings.devices.pairing.fullAccessWarning')}
            </AlertDescription>
          </Alert>
        )}
      </div>
      {expired && (
        <Alert variant="warning">
          <AlertDescription>
            {t('settings.devices.pairing.expired')}
          </AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );

  const renderWaiting = () => (
    <div className="flex flex-col gap-4">
      <p className="text-muted-foreground text-sm">
        {t('settings.devices.pairing.subtitle')}
      </p>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">
          {t('settings.devices.pairing.stepOne')}
        </span>
        <CopyField value={installCommand} />
        {/* A 12px hint line, so the link takes the hint's size and weight. */}
        <p className="text-xs">
          <Button variant="link" size="text" asChild>
            <a
              href="https://github.com/arc53/DocsGPT-cli#installation"
              target="_blank"
              rel="noreferrer"
            >
              {t('settings.devices.pairing.installLink')}
            </a>
          </Button>
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">
          {t('settings.devices.pairing.stepTwo')}
        </span>
        <CopyField value={userCode} size="display">
          {userCode || '…'}
        </CopyField>
      </div>
      <p className="text-muted-foreground text-xs">
        {t('settings.devices.pairing.waitingForCli')}
      </p>
    </div>
  );

  const footer = (() => {
    if (stage === 'form') {
      return (
        <ModalActions
          cancelLabel={t('settings.devices.pairing.cancel')}
          onCancel={close}
          submitLabel={t('settings.devices.pairing.start')}
          onSubmit={handleStart}
          pending={submitting}
        />
      );
    }
    return (
      <Button variant="ghost" size="lg" shape="pill" onClick={close}>
        {t('settings.devices.pairing.cancel')}
      </Button>
    );
  })();

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      title={t('settings.devices.pairing.title')}
      footer={footer}
    >
      {stage === 'form' && renderForm()}
      {stage === 'waiting' && renderWaiting()}
    </Modal>
  );
}
