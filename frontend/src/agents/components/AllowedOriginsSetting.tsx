import React from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FormField } from '@/components/ui/form-field';
import { Input } from '@/components/ui/input';
import { SettingRow } from '@/components/ui/setting-row';
import { Switch } from '@/components/ui/switch';

import { AgentConfig } from '../types';

/** The server refuses a longer list. */
export const MAX_ALLOWED_ORIGINS = 100;

type OriginsConfig = Pick<AgentConfig, 'restrict_origins' | 'allowed_origins'>;

/**
 * The canonical origin of what a person typed, the form the server stores and
 * browsers send: lowercase scheme and host, punycode for an international
 * host, the default port dropped. A path, query, fragment, credentials or a
 * wildcard is refused rather than dropped, so the list shows exactly what
 * will be enforced.
 */
export function parseOrigin(
  value: string,
): { origin: string } | { error: 'invalid' | 'path' } {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return { error: 'invalid' };
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { error: 'invalid' };
  }
  if (
    !url.hostname ||
    url.hostname.includes('*') ||
    url.username ||
    url.password
  ) {
    return { error: 'invalid' };
  }
  if (url.pathname !== '/' || url.search || url.hash) {
    return { error: 'path' };
  }
  return { origin: url.origin };
}

/**
 * True while the restriction is on with nothing listed: the server refuses
 * that config, so the form blocks saving until an origin is added or the
 * switch is turned off.
 */
export function originsIncomplete(config?: AgentConfig): boolean {
  return Boolean(config?.restrict_origins) && !config?.allowed_origins?.length;
}

type Props = {
  config?: AgentConfig;
  onChange: (next: OriginsConfig) => void;
  /** The caller's role can't change the policy: the state shows, disabled. */
  disabled?: boolean;
};

/**
 * The agent form's "Allowed origins" row: a switch that limits the agent's
 * API key to the listed websites, and the list itself. Turning the switch off
 * keeps the list, like the limit fields keep their numbers.
 */
export default function AllowedOriginsSetting({
  config,
  onChange,
  disabled = false,
}: Props) {
  const { t } = useTranslation();
  const switchId = React.useId();
  const [draft, setDraft] = React.useState('');
  const [error, setError] = React.useState<string | null>(null);

  const restricted = Boolean(config?.restrict_origins);
  const origins = config?.allowed_origins ?? [];
  const editable = restricted && !disabled;

  const update = (next: OriginsConfig) =>
    onChange({
      restrict_origins: restricted,
      allowed_origins: origins,
      ...next,
    });

  const add = () => {
    if (!draft.trim()) return;
    const parsed = parseOrigin(draft);
    if ('error' in parsed) {
      setError(t(`agents.form.advanced.origins.errors.${parsed.error}`));
      return;
    }
    if (origins.includes(parsed.origin)) {
      setError(
        t('agents.form.advanced.origins.errors.duplicate', {
          origin: parsed.origin,
          interpolation: { escapeValue: false },
        }),
      );
      return;
    }
    if (origins.length >= MAX_ALLOWED_ORIGINS) {
      setError(
        t('agents.form.advanced.origins.errors.full', {
          max: MAX_ALLOWED_ORIGINS,
        }),
      );
      return;
    }
    update({ allowed_origins: [...origins, parsed.origin] });
    setDraft('');
    setError(null);
  };

  const shownError =
    error ??
    (originsIncomplete(config)
      ? t('agents.form.advanced.origins.errors.required')
      : undefined);

  return (
    <SettingRow
      label={t('agents.form.advanced.origins.label')}
      description={t('agents.form.advanced.origins.description')}
      htmlFor={switchId}
      after={
        <div className="flex flex-col gap-3">
          <div className="flex items-start gap-2">
            <FormField
              className="min-w-0 flex-1"
              labelSurface="background"
              label={t('agents.form.advanced.origins.inputLabel')}
              hint={t('agents.form.advanced.origins.hint')}
              error={shownError}
              disabled={!editable}
            >
              <Input
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    add();
                  }
                }}
                placeholder={t('agents.form.advanced.origins.placeholder')}
                inputMode="url"
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
              />
            </FormField>
            <Button
              type="button"
              variant="outline"
              size="field"
              onClick={add}
              disabled={!editable || !draft.trim()}
            >
              {t('agents.form.advanced.origins.add')}
            </Button>
          </div>
          {origins.length > 0 && (
            <ul
              className="flex flex-wrap gap-2"
              aria-label={t('agents.form.advanced.origins.listLabel')}
            >
              {origins.map((origin) => (
                <li key={origin} className="max-w-full">
                  {editable ? (
                    <Badge
                      variant="neutral"
                      className="font-mono"
                      onRemove={() =>
                        update({
                          allowed_origins: origins.filter((o) => o !== origin),
                        })
                      }
                      removeLabel={t('agents.form.advanced.origins.remove', {
                        origin,
                        interpolation: { escapeValue: false },
                      })}
                    >
                      {origin}
                    </Badge>
                  ) : (
                    <Badge variant="neutral" className="font-mono">
                      {origin}
                    </Badge>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      }
    >
      <Switch
        id={switchId}
        checked={restricted}
        disabled={disabled}
        onCheckedChange={(checked) => {
          update({ restrict_origins: checked });
          setError(null);
        }}
      />
    </SettingRow>
  );
}
