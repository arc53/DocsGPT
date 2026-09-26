import { TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { baseURL } from '../api/client';
import CopyButton from '../components/CopyButton';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { NO_ESCAPE } from '../settings/accessTokenUtils';

interface AccessTokenCreatedModalProps {
  /** Plaintext secret; `null` keeps the modal closed. Held only in the parent's component state. */
  token: string | null;
  name: string;
  /** The secret replaces an existing token's secret rather than belonging to a new token. */
  regenerated?: boolean;
  onClose: () => void;
}

export default function AccessTokenCreatedModal({
  token,
  name,
  regenerated = false,
  onClose,
}: AccessTokenCreatedModalProps) {
  const { t } = useTranslation();
  const copy = regenerated
    ? 'settings.accessTokens.regenerate.done'
    : 'settings.accessTokens.created';
  const exportSnippet = `export DOCSGPT_TOKEN=${token ?? ''}`;
  const curlSnippet = `curl -H "Authorization: Bearer $DOCSGPT_TOKEN" ${baseURL}/api/get_agents`;

  return (
    <Modal
      open={token !== null}
      onOpenChange={(o) => !o && onClose()}
      title={t(`${copy}.title`)}
      description={
        <span className="break-words">
          {t(`${copy}.subtitle`, {
            name,
            ...NO_ESCAPE,
          })}
        </span>
      }
      size="lg"
      mobileVariant="sheet"
      // The secret cannot be shown again, so a stray click outside must not
      // dismiss it; closing takes the explicit button (or Esc).
      isPerformingTask
      footer={
        <Button type="button" onClick={onClose} shape="pill" size="lg">
          {t('settings.accessTokens.created.done')}
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <Alert variant="warning">
          <TriangleAlert className="size-4" aria-hidden="true" />
          <AlertDescription>
            <p>{t('settings.accessTokens.created.warning')}</p>
          </AlertDescription>
        </Alert>

        <div className="flex flex-col gap-1.5">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.accessTokens.created.tokenLabel')}
          />
          <Card
            variant="filled"
            padding="sm"
            className="flex-row items-start gap-2"
          >
            <code
              data-testid="pat-plaintext"
              className="text-foreground min-w-0 flex-1 font-mono text-xs wrap-break-word select-all"
            >
              {token}
            </code>
            {token && <CopyButton textToCopy={token} showText />}
          </Card>
        </div>

        <div className="flex flex-col gap-2">
          <SectionHeader
            as="h3"
            size="xs"
            title={t('settings.accessTokens.created.usageTitle')}
          />
          <p className="text-muted-foreground text-xs">
            {t('settings.accessTokens.created.usageHint')}
          </p>
          {[exportSnippet, curlSnippet].map((snippet, index) => (
            <Card
              key={index}
              variant="filled"
              padding="sm"
              className="flex-row items-start gap-2"
            >
              <pre className="text-foreground min-w-0 flex-1 font-mono text-xs leading-relaxed wrap-break-word whitespace-pre-wrap">
                {snippet}
              </pre>
              <CopyButton textToCopy={snippet} />
            </Card>
          ))}
        </div>
      </div>
    </Modal>
  );
}
