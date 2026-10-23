import { FileText, Globe, Trash2 } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { pageAddress } from '../components/tree/pages';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { IconButton } from '../components/ui/icon-button';
import { ListRow, ListRows } from '../components/ui/list-row';
import { LoadingState } from '../components/ui/loading-state';
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
import { selectToken } from '../preferences/preferenceSlice';
import {
  SYNC_FREQUENCIES,
  type SyncFrequency,
  type WebsiteEntry,
} from '../upload/website';
import { formatRelative } from '../utils/dateTimeUtils';

type SiteReport = { url: string; limit_reached?: boolean };

/** What a Website source fetches, skips and keeps, and how often it syncs. */
export type WebsiteSettings = {
  entries: WebsiteEntry[];
  skip: string[];
  keepLinks: boolean;
  syncFrequency: SyncFrequency;
};

/**
 * Loads a Website source's settings for Source settings.
 *
 * @param sourceId The source.
 * @param enabled Whether to load (the source is a website and the caller edits it).
 * @returns The editable settings (null while loading), their saved baseline,
 *   the crawl report, a load failure flag and a retry.
 */
export function useWebsiteSettings(sourceId: string, enabled: boolean) {
  const token = useSelector(selectToken);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const [settings, setSettings] = useState<WebsiteSettings | null>(null);
  const [baseline, setBaseline] = useState<WebsiteSettings | null>(null);
  const [reports, setReports] = useState<SiteReport[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setSettings(null);
    setBaseline(null);
    setLoadFailed(false);
    if (!enabled || !sourceId) return;
    let cancelled = false;
    userService
      .getWebsite(sourceId, tokenRef.current)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (cancelled) return;
        const loaded: WebsiteSettings = {
          entries: data.config.entries,
          skip: data.config.skip,
          keepLinks: !!data.config.keep_links,
          syncFrequency: (data.sync_frequency || 'never') as SyncFrequency,
        };
        setSettings(loaded);
        setBaseline(loaded);
        setReports(data.report?.sites ?? []);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId, enabled, reloadKey]);

  return {
    settings,
    setSettings,
    /** Whether the settings differ from what the server holds. */
    changed:
      !!settings &&
      !!baseline &&
      JSON.stringify(settings) !== JSON.stringify(baseline),
    /** Takes the current settings as saved. */
    markSaved: () => setBaseline(settings),
    reports,
    loadFailed,
    retry: () => setReloadKey((key) => key + 1),
  };
}

/**
 * The "Keep up to date" row: how often the source syncs, and when it last did.
 *
 * @param value The schedule.
 * @param onChange Picks another schedule.
 * @param syncedAt When the source was last ingested or synced.
 */
export function ScheduleRow({
  value,
  onChange,
  syncedAt,
}: {
  value: SyncFrequency;
  onChange: (value: SyncFrequency) => void;
  syncedAt?: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const lastSynced = formatRelative(syncedAt);
  return (
    <SettingRow
      label={t('modals.uploadDoc.website.sync')}
      description={
        lastSynced
          ? t('settings.sources.website.lastSynced', { when: lastSynced })
          : undefined
      }
      htmlFor={id}
    >
      <Select
        value={value}
        onValueChange={(next) => onChange(next as SyncFrequency)}
      >
        <SelectTrigger
          id={id}
          size="field"
          className="w-40"
          data-testid="source-schedule"
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {SYNC_FREQUENCIES.map((frequency) => (
            <SelectItem key={frequency} value={frequency}>
              {t(`settings.sources.syncFrequency.${frequency}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </SettingRow>
  );
}

/**
 * A Website source's own settings, the first section of its Source settings:
 * what it fetches (pages and whole sites), the addresses its crawl skips
 * (with Restore), whether page text keeps link URLs, and how often it syncs.
 * Changes apply at the next sync.
 */
export default function WebsiteSettingsFields({
  settings,
  onChange,
  reports,
  loadFailed,
  onRetry,
  syncedAt,
}: {
  /** The settings; null while they load. */
  settings: WebsiteSettings | null;
  onChange: (settings: WebsiteSettings) => void;
  reports: SiteReport[];
  loadFailed: boolean;
  onRetry: () => void;
  /** When the source was last ingested or synced. */
  syncedAt?: string;
}) {
  const { t } = useTranslation();
  const id = useId();
  const tr = (key: string, options?: Record<string, unknown>) =>
    t(`settings.sources.website.${key}`, options);
  const ur = (key: string, options?: Record<string, unknown>) =>
    t(`modals.uploadDoc.website.${key}`, options);

  if (loadFailed) {
    return (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={tr('loadFailed')}
        onRetry={onRetry}
      />
    );
  }
  if (!settings) return <LoadingState fill="block" />;

  const set = (patch: Partial<WebsiteSettings>) =>
    onChange({ ...settings, ...patch });
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

  return (
    <div className="flex flex-col gap-5">
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
        <ScheduleRow
          value={settings.syncFrequency}
          onChange={(syncFrequency) => set({ syncFrequency })}
          syncedAt={syncedAt}
        />
      </SettingRows>
      <p className="text-muted-foreground text-xs">{tr('appliesNextSync')}</p>
    </div>
  );
}
