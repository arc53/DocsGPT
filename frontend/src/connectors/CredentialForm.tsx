import { ExternalLink } from 'lucide-react';
import type { ChangeEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../components/ui/button';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import type { CredentialField } from './types';

/**
 * The short form an API-key connector asks for, generated from its catalog
 * `credential_fields` (or `setup_fields`). Secrets are masked. Labels come
 * from `settings.connectors.fields.<connector>_<key>`, then
 * `settings.connectors.fields.<key>`, then the catalog label; a field's hint
 * from `settings.connectors.fieldHints.<connector>_<key>`, then the catalog.
 * The words a hint wraps in `<link>…</link>` link to the field's `hint_url`.
 */
export default function CredentialForm({
  connectorKey,
  fields,
  values,
  onChange,
  idPrefix,
  labelSurface = 'card',
}: {
  /** Picks the connector's own label for a shared key (Telegram's "Bot token"). */
  connectorKey: string;
  fields: CredentialField[];
  values: Record<string, string>;
  onChange: (values: Record<string, string>) => void;
  idPrefix: string;
  labelSurface?: 'card' | 'background' | 'muted';
}) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-5">
      {fields.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const label = t(
          `settings.connectors.fields.${connectorKey}_${field.key}`,
          {
            defaultValue: t(`settings.connectors.fields.${field.key}`, {
              defaultValue: field.label,
            }),
          },
        );
        const inputProps = {
          id,
          type: field.secret ? 'password' : 'text',
          autoComplete: field.secret ? 'new-password' : 'off',
          value: values[field.key] ?? '',
          onChange: (e: ChangeEvent<HTMLInputElement>) =>
            onChange({ ...values, [field.key]: e.target.value }),
        };
        if (!field.hint)
          return (
            <Input
              key={field.key}
              label={label}
              labelSurface={labelSurface}
              required={field.required}
              {...inputProps}
            />
          );
        return (
          <FormField
            key={field.key}
            label={label}
            required={field.required}
            labelSurface={labelSurface}
            hint={renderHint(
              t(`settings.connectors.fieldHints.${connectorKey}_${field.key}`, {
                defaultValue: field.hint,
              }),
              field.hint_url,
            )}
          >
            <Input {...inputProps} />
          </FormField>
        );
      })}
    </div>
  );
}

const LINK_PATTERN = /<link>(.*?)<\/link>/;

/**
 * A hint's text with its `<link>…</link>` words as an inline link.
 *
 * Args:
 *   text: The translated hint.
 *   url: Where the link goes; without one the words stay plain text.
 *
 * Returns:
 *   The hint, ready for a FormField `hint`.
 */
function renderHint(text: string, url?: string | null): ReactNode {
  const match = LINK_PATTERN.exec(text);
  if (!match) return text;
  const before = text.slice(0, match.index);
  const after = text.slice(match.index + match[0].length);
  if (!url) return `${before}${match[1]}${after}`;
  return (
    <>
      {before}
      <Button variant="link" size="text" asChild>
        <a href={url} target="_blank" rel="noopener noreferrer">
          {match[1]}
          <ExternalLink className="size-3" />
        </a>
      </Button>
      {after}
    </>
  );
}

/** Whether every required field has a value. */
export const credentialsComplete = (
  fields: CredentialField[],
  values: Record<string, string>,
) => fields.every((field) => !field.required || !!values[field.key]?.trim());
