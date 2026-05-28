import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import devicesService, {
  ApprovalMode,
  PairingResponse,
} from '../api/services/devicesService';
import CopyButton from '../components/CopyButton';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
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
  const pollTimerRef = React.useRef<ReturnType<typeof setInterval> | null>(
    null,
  );

  const reset = React.useCallback(() => {
    setStage('form');
    setName('');
    setDescription('');
    setApprovalMode('ask');
    setSubmitting(false);
    setPairing(null);
    setError(null);
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
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
    setSubmitting(true);
    try {
      const trimmedName = name.trim();
      const trimmedDescription = description.trim();
      const res = await devicesService.startPairing(token, {
        name: trimmedName || undefined,
        description: trimmedDescription || undefined,
        approval_mode: approvalMode,
      });
      setPairing(res);
      setStage('waiting');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'pairing failed');
    } finally {
      setSubmitting(false);
    }
  };

  // Poll while waiting for the CLI to redeem.
  React.useEffect(() => {
    if (stage !== 'waiting' || !pairing) return;
    pollTimerRef.current = setInterval(async () => {
      try {
        const s = await devicesService.pollPairing(pairing.device_code, token);
        if (s.status === 'redeemed') {
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
          if (s.device_id && s.device_name) {
            onPaired?.(s.device_id, s.device_name);
          }
          setModalState('INACTIVE');
        }
      } catch (err) {
        console.error('pairing poll failed', err);
      }
    }, 3000);
    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
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
        labelBgClassName="bg-card"
      />
      <Input
        type="text"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        label={t('settings.devices.pairing.descriptionLabel')}
        placeholder={t('settings.devices.pairing.descriptionPlaceholder')}
        labelBgClassName="bg-card"
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
          <p className="text-xs text-red-600 dark:text-red-400">
            {t('settings.devices.pairing.fullAccessWarning')}
          </p>
        )}
      </div>
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
        <div className="bg-muted flex items-center gap-2 rounded-md p-3">
          <pre className="grow font-mono text-sm break-all whitespace-pre-wrap select-all">
            {installCommand}
          </pre>
          <CopyButton textToCopy={installCommand} />
        </div>
        <a
          href="https://github.com/arc53/DocsGPT-cli#installation"
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground text-xs underline"
        >
          {t('settings.devices.pairing.installLink')}
        </a>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-muted-foreground text-xs">
          {t('settings.devices.pairing.stepTwo')}
        </span>
        <div className="bg-muted flex items-center gap-2 rounded-md p-3">
          <div className="grow text-center font-mono text-3xl tracking-widest select-all">
            {userCode || '...'}
          </div>
          {userCode && <CopyButton textToCopy={userCode} />}
        </div>
      </div>
      <p className="text-muted-foreground text-xs">
        {t('settings.devices.pairing.waitingForCli')}
      </p>
    </div>
  );

  const footer = (() => {
    if (stage === 'form') {
      return (
        <>
          <Button variant="ghost" onClick={close} className="rounded-3xl px-5">
            {t('settings.devices.pairing.cancel')}
          </Button>
          <Button
            type="button"
            onClick={handleStart}
            disabled={submitting}
            className="rounded-3xl px-5 text-white"
          >
            {submitting
              ? t('settings.devices.pairing.starting')
              : t('settings.devices.pairing.start')}
          </Button>
        </>
      );
    }
    return (
      <Button variant="ghost" onClick={close} className="rounded-3xl px-5">
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
      contentClassName="px-1"
    >
      {stage === 'form' && renderForm()}
      {stage === 'waiting' && renderWaiting()}
    </Modal>
  );
}
