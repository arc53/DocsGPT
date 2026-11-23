import { Plus, X } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { pageAddress } from '../components/tree/pages';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { ScheduleRow } from '../settings/WebsiteSettingsFields';
import {
  type SyncFrequency,
  type WebsiteDiscovery,
  type WebsiteDraft,
  type WebsiteMode,
  normalizeUrl,
  tooManyPages,
} from './website';

const DISCOVERY: WebsiteDiscovery[] = ['auto', 'sitemap', 'links'];

/**
 * The Website source's fields: the addresses, "This page" or "Whole site",
 * a whole site's scope, whether to keep links in the page text (when
 * `keepLinks` is passed) and how often to re-fetch (when `syncFrequency` is
 * passed). Used by Add knowledge and by a source's "Add pages".
 *
 * @param draft The form's state (see `website.ts`).
 * @param onChange Receives the next draft.
 * @param maxPages The admin's cap on a source's pages (WEB_MAX_PAGES): a
 *   site's page limit, and how many addresses "This page" may list.
 * @param syncFrequency The schedule; the row is hidden without it.
 * @param onSyncFrequencyChange Receives the picked schedule.
 * @param keepLinks The source's "Keep links in page text"; the row is hidden
 *   without it.
 * @param onKeepLinksChange Receives the switch's new state.
 */
export default function WebsiteFields({
  draft,
  onChange,
  maxPages,
  syncFrequency,
  onSyncFrequencyChange,
  keepLinks,
  onKeepLinksChange,
}: {
  draft: WebsiteDraft;
  onChange: (draft: WebsiteDraft) => void;
  maxPages: number;
  syncFrequency?: SyncFrequency;
  onSyncFrequencyChange?: (value: SyncFrequency) => void;
  keepLinks?: boolean;
  onKeepLinksChange?: (value: boolean) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const hintId = `${id}-mode-hint`;
  const tr = (key: string, options?: Record<string, unknown>) =>
    t(`modals.uploadDoc.website.${key}`, options);
  const set = (patch: Partial<WebsiteDraft>) =>
    onChange({ ...draft, ...patch });
  const isSite = draft.mode === 'site';
  const showSync = !!syncFrequency && !!onSyncFrequencyChange;
  const showKeepLinks = keepLinks !== undefined && !!onKeepLinksChange;
  // A whole site starts from one address.
  const urls = isSite ? draft.urls.slice(0, 1) : draft.urls;

  const setUrl = (index: number, value: string) =>
    set({ urls: draft.urls.map((url, i) => (i === index ? value : url)) });
  // The rows the user has left: a refused address says why once its row is
  // left, not while it is still being typed.
  const [left, setLeft] = useState<ReadonlySet<number>>(() => new Set());
  const leave = (index: number) =>
    setLeft((rows) => (rows.has(index) ? rows : new Set(rows).add(index)));
  const removeUrl = (index: number) => {
    set({ urls: draft.urls.filter((_, i) => i !== index) });
    // The rows below move up one, and keep whether they were left.
    setLeft(
      (rows) =>
        new Set(
          [...rows]
            .filter((row) => row !== index)
            .map((row) => (row > index ? row - 1 : row)),
        ),
    );
  };
  const refused = (index: number, url: string) =>
    left.has(index) && !!url.trim() && !normalizeUrl(url);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3">
        {urls.map((url, index) => (
          <div key={index} className="flex items-start gap-2">
            {/* The floating label's wrapper doesn't grow by itself in a row. */}
            <FormField
              className="min-w-0 flex-1"
              label={isSite ? tr('siteUrl') : tr('pageUrl')}
              required={index === 0}
              // An address the server won't fetch (localhost, a private
              // network, no dot in the host, credentials) says why.
              error={refused(index, url) ? tr('invalidAddress') : undefined}
            >
              <Input
                type="url"
                inputMode="url"
                className="w-full"
                value={url}
                onChange={(e) => setUrl(index, e.target.value)}
                onBlur={() => leave(index)}
              />
            </FormField>
            {index > 0 && (
              <IconButton
                variant="ghost-muted"
                icon={X}
                // Named by its address, so each row's button is told apart.
                label={
                  url.trim()
                    ? tr('removeAddress', {
                        address: pageAddress(url.trim()),
                        interpolation: { escapeValue: false },
                      })
                    : tr('removePage')
                }
                onClick={() => removeUrl(index)}
              />
            )}
          </div>
        ))}
        {!isSite && (
          <Button
            type="button"
            variant="link"
            size="inline"
            className="self-start"
            onClick={() => set({ urls: [...draft.urls, ''] })}
          >
            <Plus className="size-4" />
            {tr('addAnotherPage')}
          </Button>
        )}
        {tooManyPages(draft, maxPages) && (
          <Alert variant="destructive">
            <AlertDescription>
              {t('settings.sources.website.pageLimit', { count: maxPages })}
            </AlertDescription>
          </Alert>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <ToggleGroup
          type="single"
          fill
          value={draft.mode}
          onValueChange={(value) =>
            value && set({ mode: value as WebsiteMode })
          }
          aria-label={tr('mode.label')}
          aria-describedby={hintId}
        >
          <ToggleGroupItem value="page">{tr('mode.page')}</ToggleGroupItem>
          <ToggleGroupItem value="site">{tr('mode.site')}</ToggleGroupItem>
        </ToggleGroup>
        <p id={hintId} className="text-muted-foreground text-xs">
          {isSite ? tr('mode.siteHint') : tr('mode.pageHint')}
        </p>
      </div>

      {(isSite || showSync || showKeepLinks) && (
        <SettingRows>
          {isSite && (
            <>
              <SettingRow
                label={tr('maxPages')}
                description={tr('maxPagesHint', { max: maxPages })}
                htmlFor={`${id}-max-pages`}
              >
                <Input
                  id={`${id}-max-pages`}
                  type="number"
                  min={1}
                  max={maxPages}
                  className="w-24 text-right"
                  value={String(draft.maxPages)}
                  onChange={(e) =>
                    set({ maxPages: Math.trunc(Number(e.target.value)) || 0 })
                  }
                />
              </SettingRow>
              <SettingRow
                label={tr('pathPrefix')}
                description={tr('pathPrefixHint')}
                htmlFor={`${id}-path-prefix`}
              >
                <Input
                  id={`${id}-path-prefix`}
                  className="w-40"
                  placeholder={tr('pathPrefixPlaceholder')}
                  value={draft.pathPrefix}
                  onChange={(e) => set({ pathPrefix: e.target.value })}
                />
              </SettingRow>
              <SettingRow
                label={tr('discovery.label')}
                description={tr('discovery.hint')}
                htmlFor={`${id}-discovery`}
              >
                <Select
                  value={draft.discovery}
                  onValueChange={(value) =>
                    set({ discovery: value as WebsiteDiscovery })
                  }
                >
                  <SelectTrigger
                    id={`${id}-discovery`}
                    size="field"
                    className="w-40"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DISCOVERY.map((value) => (
                      <SelectItem key={value} value={value}>
                        {tr(`discovery.${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </SettingRow>
              {draft.discovery === 'sitemap' && (
                <SettingRow
                  label={tr('sitemapUrl')}
                  description={tr('sitemapUrlHint')}
                  htmlFor={`${id}-sitemap`}
                >
                  <Input
                    id={`${id}-sitemap`}
                    type="url"
                    inputMode="url"
                    className="w-56"
                    value={draft.sitemapUrl}
                    onChange={(e) => set({ sitemapUrl: e.target.value })}
                  />
                </SettingRow>
              )}
              <SettingRow
                label={tr('includeSubdomains')}
                htmlFor={`${id}-subdomains`}
              >
                <Switch
                  id={`${id}-subdomains`}
                  checked={draft.includeSubdomains}
                  onCheckedChange={(checked) =>
                    set({ includeSubdomains: checked })
                  }
                />
              </SettingRow>
            </>
          )}
          {showKeepLinks && (
            <SettingRow
              label={tr('keepLinks')}
              description={tr('keepLinksHint')}
              htmlFor={`${id}-keep-links`}
              alignStart
            >
              <Switch
                id={`${id}-keep-links`}
                checked={keepLinks}
                onCheckedChange={onKeepLinksChange}
              />
            </SettingRow>
          )}
          {syncFrequency && onSyncFrequencyChange && (
            <ScheduleRow
              value={syncFrequency}
              onChange={onSyncFrequencyChange}
              description={isSite ? tr('syncHintSite') : tr('syncHintPage')}
            />
          )}
        </SettingRows>
      )}
    </div>
  );
}
