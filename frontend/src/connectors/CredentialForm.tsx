import type { ChangeEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import type { CredentialField } from './types';

/**
 * The short form an API-key connector asks for, generated from its catalog
 * `credential_fields` (or `setup_fields`). Secrets are masked. Labels come
 * from `settings.connectors.fields.<connector>_<key>`, then
 * `settings.connectors.fields.<key>`, then the catalog label; a field's hint
 * from `settings.connectors.fieldHints.<connector>_<key>`, then the catalog.
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
            hint={t(
              `settings.connectors.fieldHints.${connectorKey}_${field.key}`,
              { defaultValue: field.hint },
            )}
          >
            <Input {...inputProps} />
          </FormField>
        );
      })}
    </div>
  );
}

/** Whether every required field has a value. */
export const credentialsComplete = (
  fields: CredentialField[],
  values: Record<string, string>,
) => fields.every((field) => !field.required || !!values[field.key]?.trim());
