import { TriangleAlert } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import patService, {
  AccessTokenApiError,
  AccessTokenPolicy,
  CreateAccessTokenResponse,
  PersonalAccessToken,
} from '../api/services/patService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { FormField } from '../components/ui/form-field';
import { Modal, ModalActions } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { selectToken } from '../preferences/preferenceSlice';
import {
  expiryOptions,
  NO_ESCAPE,
  NO_EXPIRY,
  renewalExpiry,
} from '../settings/accessTokenUtils';
import { formatDateOnly } from '../utils/dateTimeUtils';

const DAY_MS = 24 * 60 * 60 * 1000;

interface RegenerateAccessTokenModalProps {
  /** Token to regenerate; `null` keeps the modal closed. */
  item: PersonalAccessToken | null;
  policy: AccessTokenPolicy;
  onClose: () => void;
  onRegenerated: (response: CreateAccessTokenResponse) => void;
}

export default function RegenerateAccessTokenModal({
  item,
  policy,
  onClose,
  onRegenerated,
}: RegenerateAccessTokenModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [expiry, setExpiry] = React.useState<number>(NO_EXPIRY);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const expiryChoices = React.useMemo(() => expiryOptions(policy), [policy]);

  // Preselect the lifetime the token was last issued with.
  React.useEffect(() => {
    if (!item) return;
    setExpiry(renewalExpiry(item, policy));
    setSubmitting(false);
    setError(null);
  }, [item, policy]);

  const handleClose = () => {
    if (!submitting) onClose();
  };

  const handleSubmit = async () => {
    if (!item || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      onRegenerated(await patService.regenerate(item.id, expiry, token));
    } catch (err) {
      console.error('Failed to regenerate access token:', err);
      setError(
        (err instanceof AccessTokenApiError && err.message) ||
          t('settings.accessTokens.regenerate.error'),
      );
      setSubmitting(false);
    }
  };

  const expiryLabel = (days: number) =>
    days === NO_EXPIRY
      ? t('settings.accessTokens.create.noExpiration')
      : t('settings.accessTokens.create.expiryDays', { count: days });

  return (
    <Modal
      open={item !== null}
      onOpenChange={(o) => !o && handleClose()}
      title={t('settings.accessTokens.regenerate.title')}
      description={
        <span className="break-words">
          {t('settings.accessTokens.regenerate.warning', {
            name: item?.name ?? '',
            ...NO_ESCAPE,
          })}
        </span>
      }
      size="md"
      mobileVariant="sheet"
      isPerformingTask={submitting}
      footer={
        <ModalActions
          cancelLabel={t('settings.accessTokens.create.cancel')}
          onCancel={handleClose}
          submitLabel={t('settings.accessTokens.regenerate.submit')}
          onSubmit={handleSubmit}
          pending={submitting}
          cancelProps={{ disabled: submitting }}
        />
      }
    >
      <div className="flex flex-col gap-5 px-1">
        <FormField
          id="pat-regenerate-expiry"
          label={t('settings.accessTokens.regenerate.newExpiration')}
          hint={
            expiry === NO_EXPIRY
              ? undefined
              : t('settings.accessTokens.create.expiresOn', {
                  date: formatDateOnly(
                    new Date(Date.now() + expiry * DAY_MS).toISOString(),
                  ),
                  ...NO_ESCAPE,
                })
          }
        >
          <Select
            value={String(expiry)}
            onValueChange={(value) => setExpiry(Number(value))}
          >
            <SelectTrigger
              id="pat-regenerate-expiry"
              className="w-full"
              size="lg"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {expiryChoices.map((days) => (
                <SelectItem key={days} value={String(days)}>
                  {expiryLabel(days)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {expiry === NO_EXPIRY ? (
            <Alert variant="warning">
              <TriangleAlert className="size-4" aria-hidden="true" />
              <AlertDescription>
                {t('settings.accessTokens.create.noExpirationHint')}
              </AlertDescription>
            </Alert>
          ) : null}
        </FormField>

        {error && (
          <p
            role="alert"
            className="bg-destructive/10 text-destructive rounded-lg px-4 py-2 text-sm"
          >
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
