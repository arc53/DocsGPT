import { FileText, Globe, Trash2 } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { pageAddress } from '../components/tree/pages';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { Doc } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import {
  SYNC_FREQUENCIES,
  type SyncFrequency,
  type WebsiteEntry,
} from '../upload/website';
import { formatRelative } from '../utils/dateTimeUtils';

type SiteReport = { url: string; limit_reached?: boolean };

type WebsiteSettings = {
  entries: WebsiteEntry[];
  skip: string[];
  keepLinks: boolean;
  syncFrequency: SyncFrequency;
};

/**
 * A Website source's settings: what it fetches (pages and whole sites), the
 * addresses its crawl skips (with Restore), whether page text keeps link
 * URLs, and how often it syncs. Changes apply at the next sync; Sync now
 * runs one.
 *
 * @param document The source.
 * @param onClose Closes the dialog.
 * @param onSaved Called after a save, to re-read the list.
 * @param onSyncNow Starts a sync of the source.
 */
export default function WebsiteSettingsModal({
  document,
  onClose,
  onSaved,
  onSyncNow,
}: {
  document: Doc;
  onClose: () => void;
  onSaved: () => void;
  onSyncNow: () => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const id = useId();
  const tr = (key: string, options?: Record<string, unknown>) =>
    t(`settings.sources.website.${key}`, options);
  const ur = (key: string, options?: Record<string, unknown>) =>
    t(`modals.uploadDoc.website.${key}`, options);

  const [settings, setSettings] = useState<WebsiteSettings | null>(null);
  const [reports, setReports] = useState<SiteReport[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);

  const sourceId = document.id ?? '';
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    let cancelled = false;
    setSettings(null);
    setLoadFailed(false);
    userService
      .getWebsite(sourceId, tokenRef.current)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (cancelled) return;
        setSettings({
          entries: data.config.entries,
          skip: data.config.skip,
          keepLinks: !!data.config.keep_links,
          syncFrequency: (data.sync_frequency || 'never') as SyncFrequency,
        });
        setReports(data.report?.sites ?? []);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId, reloadKey]);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setSaveFailed(false);
    try {
      const response = await userService.saveWebsite(
        {
          source_id: sourceId,
          entries: settings.entries,
          skip: settings.skip,
          keep_links: settings.keepLinks,
          sync_frequency: settings.syncFrequency,
        },
        token,
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      onSaved();
      onClose();
    } catch {
      setSaveFailed(true);
    } finally {
      setSaving(false);
    }
  };

  const describe = (entry: WebsiteEntry) => {
    if (entry.mode === 'page') return tr('pageEntry');
    const summary = tr('siteSummary', {
      find: ur(`discovery.${entry.discovery ?? 'auto'}`),
      max: entry.max_pages ?? '—',
    });
    const reached = reports.some(
      (report) => report.url === entry.url && report.limit_reached,
    );
    return reached ? `${summary} · ${tr('limitReached')}` : summary;
  };

  const body = () => {
    if (loadFailed) {
      return (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={tr('loadFailed')}
          onRetry={() => setReloadKey((key) => key + 1)}
        />
      );
    }
    if (!settings) return <LoadingState fill="block" />;
    const set = (patch: Partial<WebsiteSettings>) =>
      setSettings({ ...settings, ...patch });
    const lastSynced = formatRelative(document.date);
    return (
      <div className="flex flex-col gap-5">
        {saveFailed && (
          <Alert variant="destructive">
            <AlertDescription>{tr('saveFailed')}</AlertDescription>
          </Alert>
        )}
        <div className="flex flex-col gap-2">
          <SectionHeader size="sm" title={tr('fetches')} />
          <Card variant="outline" padding="none">
            <ListRows>
              {settings.entries.map((entry, index) => {
                const Icon = entry.mode === 'site' ? Globe : FileText;
                return (
                  <ListRow
                    key={`${entry.mode}-${entry.url}`}
                    leading={
                      <Icon
                        aria-hidden="true"
                        className="text-muted-foreground size-4"
                      />
                    }
                    title={
                      <span title={entry.url}>{pageAddress(entry.url)}</span>
                    }
                    description={describe(entry)}
                    trailing={
                      <IconButton
                        variant="ghost-destructive"
                        size="icon-sm"
                        icon={Trash2}
                        label={tr('removeFromList')}
                        // A source must keep something to fetch.
                        disabled={settings.entries.length === 1}
                        onClick={() =>
                          set({
                            entries: settings.entries.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      />
                    }
                  />
                );
              })}
            </ListRows>
          </Card>
        </div>
        {settings.skip.length > 0 && (
          <div className="flex flex-col gap-2">
            <SectionHeader
              size="sm"
              title={tr('skipped')}
              count={settings.skip.length}
            />
            <Card variant="outline" padding="none">
              <ListRows>
                {settings.skip.map((rule) => (
                  <ListRow
                    key={rule}
                    title={<span title={rule}>{pageAddress(rule)}</span>}
                    trailing={
                      <Button
                        type="button"
                        variant="link"
                        size="inline"
                        onClick={() =>
                          set({ skip: settings.skip.filter((r) => r !== rule) })
                        }
                      >
                        {tr('restore')}
                      </Button>
                    }
                  />
                ))}
              </ListRows>
            </Card>
          </div>
        )}
        <SettingRows>
          <SettingRow
            label={ur('keepLinks')}
            description={ur('keepLinksHint')}
            htmlFor={`${id}-links`}
            alignStart
          >
            <Switch
              id={`${id}-links`}
              checked={settings.keepLinks}
              onCheckedChange={(checked) => set({ keepLinks: checked })}
            />
          </SettingRow>
          <SettingRow
            label={ur('sync')}
            description={
              lastSynced ? tr('lastSynced', { when: lastSynced }) : undefined
            }
            htmlFor={`${id}-sync`}
          >
            <Select
              value={settings.syncFrequency}
              onValueChange={(value) =>
                set({ syncFrequency: value as SyncFrequency })
              }
            >
              <SelectTrigger id={`${id}-sync`} size="field" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SYNC_FREQUENCIES.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`settings.sources.syncFrequency.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </SettingRow>
        </SettingRows>
        <p className="text-muted-foreground text-xs">{tr('appliesNextSync')}</p>
      </div>
    );
  };

  return (
    <Modal
      open={true}
      onOpenChange={(open) => !open && onClose()}
      title={tr('settingsTitle')}
      description={document.name}
      size="lg"
      footer={
        <ModalActions
          cancelLabel={t('cancel')}
          onCancel={onClose}
          submitLabel={tr('save')}
          onSubmit={save}
          pending={saving}
          disabled={!settings}
          footerStart={
            <Button
              type="button"
              variant="outline"
              size="lg"
              shape="pill"
              onClick={() => {
                onSyncNow();
                onClose();
              }}
            >
              {t('settings.sources.syncNow')}
            </Button>
          }
        />
      }
    >
      {body()}
    </Modal>
  );
}
