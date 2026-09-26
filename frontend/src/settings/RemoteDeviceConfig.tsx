import { ShieldAlert } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import devicesService, {
  ApprovalMode,
  AuditEntry,
  Device,
} from '../api/services/devicesService';
import CopyButton from '../components/CopyButton';
import ToolIcon from '../components/ToolIcon';
import DetailBreadcrumb from '../navigation/DetailBreadcrumb';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { LoadingState } from '../components/ui/loading-state';
import { SectionHeader } from '../components/ui/section-header';
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
import { formatDateTime } from '../utils/dateTimeUtils';
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
  return value ? formatDateTime(value) : '-';
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
    return <LoadingState fill="block" size="lg" />;
  }

  return (
    <div className="scrollbar-overlay flex flex-col gap-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <DetailBreadcrumb
          parentLabel={t('settings.tools.label')}
          currentLabel={
            device?.name || tool.customName || tool.displayName || tool.name
          }
          onParentClick={handleGoBack}
        />
        <Button
          type="button"
          size="sm"
          shape="pill"
          onClick={handleSaveChanges}
          disabled={!hasUnsavedChanges || loading}
          loading={saving}
        >
          {t('settings.tools.save')}
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <ToolIcon
          name={tool.name}
          title={t('settings.tools.toolIconTitle', { name: tool.displayName })}
          className="size-7"
        />
        <h2 className="text-foreground text-xl leading-tight font-semibold">
          {device?.name ||
            tool.customName ||
            tool.displayName ||
            t('settings.devices.fallbackName')}
        </h2>
        <Badge variant={online ? 'success' : 'neutral'}>{pillText}</Badge>
        {approvalMode === 'full' && (
          <Badge variant="destructive">
            {t('settings.devices.approvalFull')}
          </Badge>
        )}
      </div>

      {/* Identity */}
      <section className="flex flex-col gap-5">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.devices.identity')}
        />
        <FormField
          label={t('settings.devices.nameLabel')}
          labelSurface="background"
          className="w-full max-w-[340px]"
        >
          <Input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
        <FormField
          label={t('settings.devices.descriptionLabel')}
          labelSurface="background"
          className="w-full max-w-[340px]"
        >
          <Input
            type="text"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('settings.devices.descriptionPlaceholder')}
          />
        </FormField>
      </section>

      {/* Access */}
      <section className="flex flex-col gap-5">
        <SectionHeader as="h3" size="xs" title={t('settings.devices.access')} />
        <div className="flex w-full max-w-[340px] flex-col gap-2">
          <FormField
            label={t('settings.devices.approvalMode')}
            labelSurface="background"
            hint={
              approvalMode === 'full'
                ? t('settings.devices.approvalFullDescription')
                : t('settings.devices.approvalAskDescription')
            }
          >
            <Select
              value={approvalMode}
              onValueChange={(value) => setApprovalMode(value as ApprovalMode)}
            >
              <SelectTrigger className="w-full" size="field">
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
          </FormField>
          {approvalMode === 'full' && (
            <Alert variant="destructive">
              <ShieldAlert className="size-4" aria-hidden="true" />
              <AlertDescription>
                {t('settings.devices.fullAccessWarning')}
              </AlertDescription>
            </Alert>
          )}
        </div>
      </section>

      {/* Connection */}
      <section className="flex flex-col gap-4">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.devices.connection')}
        />
        <DescriptionList layout="columns" size="sm">
          <DescriptionItem label={t('settings.devices.hostLabel')}>
            <span className="font-mono text-xs">
              {device?.hostname || 'unknown host'}
            </span>
            {device?.os ? ` · ${device.os}` : ''}
            {device?.arch ? ` · ${device.arch}` : ''}
            {device?.cli_version ? ` · cli ${device.cli_version}` : ''}
          </DescriptionItem>
          <DescriptionItem label={t('settings.devices.deviceIdLabel')}>
            <div className="flex flex-wrap items-center gap-2">
              <code className="text-foreground bg-muted max-w-full truncate rounded px-2 py-0.5 font-mono text-xs">
                {deviceId || '-'}
              </code>
              {deviceId && <CopyButton textToCopy={deviceId} />}
            </div>
          </DescriptionItem>
          <DescriptionItem label={t('settings.devices.lastSeenLabel')}>
            {formatTimestamp(device?.last_seen_at)}
          </DescriptionItem>
        </DescriptionList>
        {!online && (
          <p className="text-muted-foreground text-xs">
            {t('settings.devices.offlineHint')}
          </p>
        )}
      </section>

      {/* Recent activity */}
      <section className="flex flex-col gap-3">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.devices.auditTitle')}
        />
        <div className="border-border w-full rounded-xl border">
          <Accordion
            type="single"
            collapsible
            onValueChange={handleAuditToggle}
          >
            <AccordionItem value="audit">
              <AccordionTrigger>
                {t('settings.devices.auditTitle')}
                {audit !== null ? ` (${audit.length})` : ''}
              </AccordionTrigger>
              <AccordionContent>
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
                        className="bg-muted flex flex-col gap-1 rounded-md px-3 py-2 text-xs"
                      >
                        <code className="text-foreground block font-mono break-all whitespace-pre-wrap">
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
                            {t('settings.devices.auditDurationValue', {
                              value: entry.duration_ms ?? '-',
                            })}
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
        </div>
      </section>

      {/* Danger zone */}
      <section className="flex flex-col gap-3">
        <SectionHeader
          as="h3"
          size="xs"
          tone="destructive"
          title={t('settings.devices.dangerZone')}
        />
        <Card
          tone="destructive"
          className="sm:flex-row sm:items-center sm:justify-between"
        >
          <p className="text-muted-foreground text-sm">
            {t('settings.devices.dangerZoneDescription')}
          </p>
          <Button
            type="button"
            variant="destructive-outline"
            shape="pill"
            className="shrink-0"
            onClick={() => setRevokeState('ACTIVE')}
          >
            {t('settings.devices.revoke')}
          </Button>
        </Card>
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
        variant="destructive"
      />
    </div>
  );
}
