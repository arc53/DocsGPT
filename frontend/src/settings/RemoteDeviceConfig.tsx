import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import devicesService, {
  ApprovalMode,
  AuditEntry,
  Device,
} from '../api/services/devicesService';
import ArrowLeft from '../assets/arrow-left.svg';
import CopyButton from '../components/CopyButton';
import Spinner from '../components/Spinner';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { UserToolType } from './types';

/** ms-since-last-seen threshold for the online pill. */
const ONLINE_WINDOW_MS = 30_000;

function isOnline(device: Device | null): boolean {
  if (!device?.last_seen_at) return false;
  const t = Date.parse(device.last_seen_at);
  if (Number.isNaN(t)) return false;
  return Date.now() - t < ONLINE_WINDOW_MS;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

/** Compact relative span (e.g. "12s", "5m", "3h", "2d") since `value`. */
function formatRelative(value: string | null | undefined): string | null {
  if (!value) return null;
  const t = Date.parse(value);
  if (Number.isNaN(t)) return null;
  const diff = Math.max(0, Date.now() - t);
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

interface Props {
  tool: UserToolType;
  handleGoBack: () => void;
}

export default function RemoteDeviceConfig({ tool, handleGoBack }: Props) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const deviceId = React.useMemo(
    () => (tool.config?.device_id as string | undefined) || '',
    [tool.config?.device_id],
  );

  const [device, setDevice] = React.useState<Device | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [name, setName] = React.useState<string>('');
  const [description, setDescription] = React.useState<string>('');
  const [approvalMode, setApprovalMode] = React.useState<ApprovalMode>('ask');
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const [audit, setAudit] = React.useState<AuditEntry[] | null>(null);
  const [auditLoading, setAuditLoading] = React.useState(false);

  const [revokeState, setRevokeState] = React.useState<ActiveState>('INACTIVE');

  const applyDevice = React.useCallback((d: Device) => {
    setDevice(d);
    setName(d.name || '');
    setDescription(d.description || '');
    setApprovalMode(d.approval_mode);
  }, []);

  const loadDevice = React.useCallback(() => {
    if (!deviceId) return;
    setLoading(true);
    devicesService
      .get(deviceId, token)
      .then((d) => applyDevice(d))
      .catch((err) => {
        console.error('load device failed', err);
        setError(err instanceof Error ? err.message : 'load failed');
      })
      .finally(() => setLoading(false));
  }, [deviceId, token, applyDevice]);

  React.useEffect(() => {
    loadDevice();
  }, [loadDevice]);

  const loadAudit = React.useCallback(() => {
    if (!deviceId) return;
    setAuditLoading(true);
    devicesService
      .listAudit(deviceId, token)
      .then((res) => setAudit(res.entries || []))
      .catch((err) => {
        console.error('load audit failed', err);
        setAudit([]);
      })
      .finally(() => setAuditLoading(false));
  }, [deviceId, token]);

  const handleAuditToggle = (value: string) => {
    // Radix Accordion (type="single") passes the open item id, or empty
    // when closed. Lazy-fetch on first open.
    if (value === 'audit' && audit === null) {
      loadAudit();
    }
  };

  const hasUnsavedChanges =
    !!device &&
    !!name.trim() &&
    ((device.name || '') !== name ||
      (device.description || '') !== description ||
      device.approval_mode !== approvalMode);

  const handleSaveChanges = async () => {
    if (!deviceId || !device || !hasUnsavedChanges) return;
    const payload: Partial<
      Pick<Device, 'name' | 'description' | 'approval_mode'>
    > = {};
    if ((device.name || '') !== name) payload.name = name;
    if ((device.description || '') !== description)
      payload.description = description;
    if (device.approval_mode !== approvalMode)
      payload.approval_mode = approvalMode;

    setSaving(true);
    setError(null);
    try {
      const next = await devicesService.update(deviceId, payload, token);
      applyDevice(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'update failed');
    } finally {
      setSaving(false);
    }
  };

  const handleRevoke = async () => {
    if (!deviceId) return;
    try {
      await devicesService.revoke(deviceId, token);
      setRevokeState('INACTIVE');
      handleGoBack();
    } catch (err) {
      console.error('revoke failed', err);
      setRevokeState('INACTIVE');
    }
  };

  const online = isOnline(device);
  const lastSeenAgo = formatRelative(device?.last_seen_at);
  const pillText =
    (online ? t('settings.devices.online') : t('settings.devices.offline')) +
    (lastSeenAgo
      ? ` · ${t('settings.devices.seenAgo', { time: lastSeenAgo })}`
      : '');

  if (loading && !device) {
    return (
      <div className="mt-8 flex items-center justify-center py-16">
        <Spinner size="large" />
      </div>
    );
  }

  return (
    <div className="scrollbar-overlay mt-8 flex flex-col gap-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="text-foreground dark:text-foreground flex items-center gap-3 text-sm">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="text-muted-foreground rounded-full p-3"
            onClick={handleGoBack}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
          </Button>
          <p className="mt-px">{t('settings.tools.backToAllTools')}</p>
        </div>
        <Button
          type="button"
          className="rounded-full px-3 py-2 text-xs text-nowrap text-white sm:px-4 sm:py-2"
          onClick={handleSaveChanges}
          disabled={!hasUnsavedChanges || saving || loading}
        >
          {saving ? t('settings.tools.saving') : t('settings.tools.save')}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <img
          src={`/toolIcons/tool_${tool.name}.svg`}
          alt={`${tool.displayName} icon`}
          className="h-7 w-7"
        />
        <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
          {device?.name || tool.customName || tool.displayName || 'device'}
        </h2>
        <span
          className={`rounded-full px-3 py-0.5 text-xs font-medium ${
            online
              ? 'bg-green-100 text-green-900 dark:bg-green-900/30 dark:text-green-300'
              : 'bg-gray-200 text-gray-700 dark:bg-gray-700/40 dark:text-gray-300'
          }`}
        >
          {pillText}
        </span>
        {approvalMode === 'full' && (
          <span className="rounded-full bg-red-200 px-3 py-0.5 text-xs font-medium text-red-900 dark:bg-red-900/40 dark:text-red-300">
            {t('settings.devices.approvalFull')}
          </span>
        )}
      </div>

      {/* Identity */}
      <section className="flex flex-col gap-4">
        <h3 className="text-foreground dark:text-foreground text-sm font-semibold">
          {t('settings.devices.identity')}
        </h3>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <label className="text-muted-foreground w-32 shrink-0 pt-2 text-sm">
            {t('settings.devices.nameLabel')}
          </label>
          <div className="w-full max-w-[340px]">
            <Input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('settings.devices.nameLabel')}
              className="rounded-xl"
            />
          </div>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <label className="text-muted-foreground w-32 shrink-0 pt-2 text-sm">
            {t('settings.devices.descriptionLabel')}
          </label>
          <div className="w-full max-w-[340px]">
            <Input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t('settings.devices.descriptionPlaceholder')}
              className="rounded-xl"
            />
          </div>
        </div>
      </section>

      {/* Access */}
      <section className="flex flex-col gap-4">
        <h3 className="text-foreground dark:text-foreground text-sm font-semibold">
          {t('settings.devices.access')}
        </h3>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <label className="text-muted-foreground w-32 shrink-0 pt-2 text-sm">
            {t('settings.devices.approvalMode')}
          </label>
          <div className="flex w-full max-w-[340px] flex-col gap-2">
            <Select
              value={approvalMode}
              onValueChange={(value) => setApprovalMode(value as ApprovalMode)}
            >
              <SelectTrigger className="w-full rounded-xl px-4 py-2" size="lg">
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
            <p className="text-muted-foreground text-xs">
              {approvalMode === 'full'
                ? t('settings.devices.approvalFullDescription')
                : t('settings.devices.approvalAskDescription')}
            </p>
            {approvalMode === 'full' && (
              <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600 dark:bg-red-900/20 dark:text-red-400">
                {t('settings.devices.fullAccessWarning')}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Connection */}
      <section className="flex flex-col gap-4">
        <h3 className="text-foreground dark:text-foreground text-sm font-semibold">
          {t('settings.devices.connection')}
        </h3>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <span className="text-muted-foreground w-32 shrink-0 pt-px text-sm">
            {t('settings.devices.hostLabel')}
          </span>
          <div className="text-muted-foreground w-full max-w-md text-sm">
            <span className="font-mono">
              {device?.hostname || 'unknown host'}
            </span>
            {device?.os ? ` · ${device.os}` : ''}
            {device?.arch ? ` · ${device.arch}` : ''}
            {device?.cli_version ? ` · cli ${device.cli_version}` : ''}
          </div>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <span className="text-muted-foreground w-32 shrink-0 pt-1 text-sm">
            {t('settings.devices.deviceIdLabel')}
          </span>
          <div className="flex w-full max-w-md flex-wrap items-center gap-2">
            <code className="text-foreground dark:text-foreground bg-muted max-w-full truncate rounded px-2 py-0.5 font-mono text-xs">
              {deviceId || '-'}
            </code>
            {deviceId && <CopyButton textToCopy={deviceId} />}
          </div>
        </div>
        <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:gap-4">
          <span className="text-muted-foreground w-32 shrink-0 pt-px text-sm">
            {t('settings.devices.lastSeenLabel')}
          </span>
          <div className="text-muted-foreground w-full max-w-md text-sm">
            {formatTimestamp(device?.last_seen_at)}
          </div>
        </div>
        {!online && (
          <p className="text-muted-foreground text-xs">
            {t('settings.devices.offlineHint')}
          </p>
        )}
      </section>

      {/* Recent activity */}
      <section className="flex flex-col gap-3">
        <h3 className="text-foreground dark:text-foreground text-sm font-semibold">
          {t('settings.devices.auditTitle')}
        </h3>
        <Accordion
          type="single"
          collapsible
          onValueChange={handleAuditToggle}
          className="border-border dark:border-border w-full rounded-xl border"
        >
          <AccordionItem value="audit" className="border-b-0">
            <AccordionTrigger className="px-4 py-3 text-sm font-semibold">
              {t('settings.devices.auditTitle')}
              {audit !== null ? ` (${audit.length})` : ''}
            </AccordionTrigger>
            <AccordionContent className="px-4 pb-4">
              {auditLoading ? (
                <p className="text-muted-foreground py-2 text-sm">
                  {t('settings.devices.auditLoading')}
                </p>
              ) : !audit || audit.length === 0 ? (
                <p className="text-muted-foreground py-2 text-sm">
                  {t('settings.devices.auditEmpty')}
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {audit.map((entry) => (
                    <li
                      key={entry.id}
                      className="bg-muted/40 flex flex-col gap-1 rounded-md px-3 py-2 text-xs"
                    >
                      <code className="text-foreground dark:text-foreground block font-mono break-all whitespace-pre-wrap">
                        {entry.command}
                      </code>
                      <div className="text-muted-foreground flex flex-wrap gap-3">
                        <span>
                          {t('settings.devices.auditDecision')}:{' '}
                          {entry.decision}
                        </span>
                        <span>
                          {t('settings.devices.auditExit')}:{' '}
                          {entry.exit_code ?? '-'}
                        </span>
                        <span>
                          {t('settings.devices.auditDuration')}:{' '}
                          {entry.duration_ms ?? '-'} ms
                        </span>
                        <span>{formatTimestamp(entry.created_at)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </section>

      {/* Danger zone */}
      <section className="flex flex-col gap-3">
        <h3 className="text-destructive text-sm font-semibold">
          {t('settings.devices.dangerZone')}
        </h3>
        <div className="border-destructive/40 flex flex-col gap-3 rounded-xl border p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-muted-foreground text-sm">
            {t('settings.devices.dangerZoneDescription')}
          </p>
          <Button
            type="button"
            variant="destructive"
            className="shrink-0 rounded-full px-5 text-white"
            onClick={() => setRevokeState('ACTIVE')}
          >
            {t('settings.devices.revoke')}
          </Button>
        </div>
      </section>

      <ConfirmationModal
        message={
          device
            ? t('settings.devices.revokeWarning', { name: device.name })
            : ''
        }
        modalState={revokeState}
        setModalState={setRevokeState}
        handleSubmit={handleRevoke}
        submitLabel={t('settings.devices.revoke')}
        variant="danger"
      />
    </div>
  );
}
