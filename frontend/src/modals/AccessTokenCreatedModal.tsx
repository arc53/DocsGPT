import { TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { baseURL } from '../api/client';
import CopyButton from '../components/CopyButton';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { NO_ESCAPE } from '../settings/accessTokenUtils';

interface AccessTokenCreatedModalProps {
  /** Plaintext secret; `null` keeps the modal closed. Held only in the parent's component state. */
  token: string | null;
  name: string;
  onClose: () => void;
}

export default function AccessTokenCreatedModal({
  token,
  name,
  onClose,
}: AccessTokenCreatedModalProps) {
  const { t } = useTranslation();
  const exportSnippet = `export DOCSGPT_TOKEN=${token ?? ''}`;
  const curlSnippet = `curl -H "Authorization: Bearer $DOCSGPT_TOKEN" ${baseURL}/api/get_agents`;

  return (
    <Modal
      open={token !== null}
      onOpenChange={(o) => !o && onClose()}
      hideTitle
      title={t('settings.accessTokens.created.title')}
      size="lg"
      mobileVariant="sheet"
      // The secret cannot be shown again, so a stray click outside must not
      // dismiss it; closing takes the explicit button (or Esc).
      isPerformingTask
      footer={
        <Button
          type="button"
          onClick={onClose}
          className="rounded-3xl px-6 text-white"
        >
          {t('settings.accessTokens.created.done')}
        </Button>
      }
    >
      <div className="flex flex-col gap-5 px-1">
        <div>
          <h2 className="text-foreground dark:text-foreground text-xl font-semibold">
            {t('settings.accessTokens.created.title')}
          </h2>
          <p className="text-muted-foreground mt-2 text-sm break-words">
            {t('settings.accessTokens.created.subtitle', {
              name,
              ...NO_ESCAPE,
            })}
          </p>
        </div>

        <div
          role="alert"
          className="flex items-start gap-3 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:bg-amber-900/20 dark:text-amber-300"
        >
          <TriangleAlert
            className="mt-0.5 size-4 shrink-0"
            aria-hidden="true"
          />
          <p>{t('settings.accessTokens.created.warning')}</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <p className="text-foreground dark:text-foreground text-sm font-semibold">
            {t('settings.accessTokens.created.tokenLabel')}
          </p>
          <div className="bg-muted flex items-center gap-2 rounded-xl py-2 pr-2 pl-4">
            <code
              data-testid="pat-plaintext"
              className="text-foreground dark:text-foreground min-w-0 flex-1 font-mono text-xs break-all select-all sm:text-sm"
            >
              {token}
            </code>
            {token && <CopyButton textToCopy={token} showText />}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-foreground dark:text-foreground text-sm font-semibold">
            {t('settings.accessTokens.created.usageTitle')}
          </p>
          <p className="text-muted-foreground text-xs">
            {t('settings.accessTokens.created.usageHint')}
          </p>
          {[exportSnippet, curlSnippet].map((snippet, index) => (
            <div
              key={index}
              className="bg-muted flex items-start gap-2 rounded-xl py-2 pr-2 pl-4"
            >
              <pre className="text-foreground dark:text-foreground min-w-0 flex-1 font-mono text-xs leading-relaxed break-all whitespace-pre-wrap">
                {snippet}
              </pre>
              <CopyButton textToCopy={snippet} />
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
}
