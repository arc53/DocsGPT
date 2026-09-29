import { Lock } from 'lucide-react';
import type React from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from './ui/alert';

/**
 * The first child of a form the caller's role can only view: the same
 * fields, disabled, under one quiet note. Every view-only form shows this
 * one sentence, so a role reads the same everywhere. `message` replaces it
 * only where part of an editable form is locked (a tool's credentials).
 */
export default function ViewOnlyNotice({
  message,
  ...props
}: Omit<React.ComponentProps<typeof Alert>, 'children' | 'variant'> & {
  message?: string;
}) {
  const { t } = useTranslation();
  return (
    <Alert role="note" {...props}>
      <Lock />
      <AlertDescription>
        {message ?? t('common.viewOnlyNotice')}
      </AlertDescription>
    </Alert>
  );
}
