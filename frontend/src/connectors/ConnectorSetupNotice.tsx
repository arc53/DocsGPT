import { ExternalLink, TriangleAlert } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import type { ConnectorDefinition } from './types';

/**
 * "Needs admin setup" for a connector that still lacks server settings:
 * the missing setting names for an admin, "ask your admin" for everyone
 * else, and the setup guide when there is one.
 */
export default function ConnectorSetupNotice({
  connector,
}: {
  connector: Pick<ConnectorDefinition, 'missing_settings' | 'docs_url'>;
}) {
  const { t } = useTranslation();
  return (
    <Alert variant="warning">
      <TriangleAlert />
      <AlertTitle>{t('settings.connectors.status.needsAdminSetup')}</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-2">
          {connector.missing_settings.length > 0 ? (
            <>
              <span>{t('settings.connectors.setupSettings')}</span>
              <code className="font-mono text-xs wrap-anywhere">
                {connector.missing_settings.join(', ')}
              </code>
            </>
          ) : (
            <span>{t('settings.connectors.askAdmin')}</span>
          )}
          {connector.docs_url && (
            <Button
              variant="link"
              size="text"
              tone="current"
              asChild
              className="w-fit"
            >
              <a
                href={connector.docs_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                {t('settings.connectors.setupGuide')}
                <ExternalLink />
              </a>
            </Button>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}
