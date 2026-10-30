import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { baseURL } from '../api/client';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { CopyField } from '../components/ui/code-block';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { NO_ESCAPE } from '../settings/accessTokenUtils';

interface AccessTokenCreatedModalProps {
  /** Plaintext secret; `null` keeps the modal closed. Held only in the parent's component state. */
  token: string | null;
  name: string;
  /** The secret replaces an existing token's secret rather than belonging to a new token. */
  regenerated?: boolean;
  /**
   * Creates an API tool that lets agents read the account with this token.
   * Unset hides the option (a token that can read nothing agents use).
   */
  onCreateTool?: () => Promise<void>;
  onClose: () => void;
}

export default function AccessTokenCreatedModal({
  token,
  name,
  regenerated = false,
  onCreateTool,
  onClose,
}: AccessTokenCreatedModalProps) {
  const { t } = useTranslation();
  const [toolState, setToolState] = useState<
    'idle' | 'creating' | 'created' | 'failed'
  >('idle');
  const [toolError, setToolError] = useState('');
  const createTool = async () => {
    if (!onCreateTool) return;
    setToolState('creating');
    try {
      await onCreateTool();
      setToolState('created');
    } catch (err) {
      setToolError(err instanceof Error ? err.message : '');
      setToolState('failed');
    }
  };
  const close = () => {
    setToolState('idle');
    setToolError('');
    onClose();
  };
  const copy = regenerated
    ? 'settings.accessTokens.regenerate.done'
    : 'settings.accessTokens.created';
  const exportSnippet = `export DOCSGPT_TOKEN=${token ?? ''}`;
  const curlSnippet = `curl -H "Authorization: Bearer $DOCSGPT_TOKEN" ${baseURL}/api/get_agents`;

  return (
    <Modal
      open={token !== null}
      onOpenChange={(o) => !o && close()}
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
      // The secret cannot be shown again, so a stray click outside must not
      // dismiss it; closing takes the explicit button (or Esc).
      isPerformingTask
      footer={
        <Button type="button" onClick={close} shape="pill" size="lg">
          {t('settings.accessTokens.created.done')}
        </Button>
      }
    >
      <div className="flex flex-col gap-5">
        <Alert variant="warning">
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
          <CopyField
            value={token ?? ''}
            wrap="anywhere"
            data-testid="pat-plaintext"
          />
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
            <CopyField key={index} value={snippet} />
          ))}
        </div>

        {onCreateTool && (
          <div className="flex flex-col gap-2">
            {toolState === 'created' ? (
              <Alert variant="success">
                <AlertDescription>
                  <p>{t('settings.accessTokens.created.toolCreated')}</p>
                </AlertDescription>
              </Alert>
            ) : (
              <Button
                type="button"
                variant="outline"
                shape="pill"
                className="w-fit"
                disabled={toolState === 'creating'}
                onClick={createTool}
              >
                {t('settings.accessTokens.created.createTool')}
              </Button>
            )}
            {toolState === 'failed' && (
              <Alert variant="destructive">
                <AlertDescription>
                  <p>
                    {toolError || t('settings.accessTokens.created.toolFailed')}
                  </p>
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}
