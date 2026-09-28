import { useTranslation } from 'react-i18next';

import { Input } from '../components/ui/input';
import type { CredentialField } from './types';

/**
 * The short form an API-key connector asks for, generated from its catalog
 * `credential_fields` (or `setup_fields`). Secrets are masked. Labels come
 * from `settings.connectors.fields.<connector>_<key>`, then
 * `settings.connectors.fields.<key>`, then the catalog label.
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
      {fields.map((field) => (
        <Input
          key={field.key}
          id={`${idPrefix}-${field.key}`}
          label={t(`settings.connectors.fields.${connectorKey}_${field.key}`, {
            defaultValue: t(`settings.connectors.fields.${field.key}`, {
              defaultValue: field.label,
            }),
          })}
          labelSurface={labelSurface}
          type={field.secret ? 'password' : 'text'}
          autoComplete={field.secret ? 'new-password' : 'off'}
          required={field.required}
          value={values[field.key] ?? ''}
          onChange={(e) => onChange({ ...values, [field.key]: e.target.value })}
        />
      ))}
    </div>
  );
}

/** Whether every required field has a value. */
export const credentialsComplete = (
  fields: CredentialField[],
  values: Record<string, string>,
) => fields.every((field) => !field.required || !!values[field.key]?.trim());
