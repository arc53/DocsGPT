import { useTranslation } from 'react-i18next';
import ConnectorAuth from './ConnectorAuth';
import { useEffect, useState } from 'react';

import {
  getSessionToken,
  setSessionToken,
  removeSessionToken,
  validateProviderSession,
} from '../utils/providerUtils';
import ConnectedStateSkeleton from './ConnectedStateSkeleton';
import FilesSectionSkeleton from './FileSelectionSkeleton';

interface SharePointPickerProps {
  token: string | null;
}

const SharePointPicker: React.FC<SharePointPickerProps> = ({ token }) => {
  const { t } = useTranslation();
  const [isLoading, setIsLoading] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [authError, setAuthError] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  useEffect(() => {
    const sessionToken = getSessionToken('share_point');
    if (sessionToken) {
      setIsValidating(true);
      setIsConnected(true); // Optimistically set as connected for skeleton
      validateSession(sessionToken);
    }
  }, [token]);

  const validateSession = async (sessionToken: string) => {
    try {
      const validateResponse = await validateProviderSession(
        token,
        'share_point',
      );

      if (!validateResponse.ok) {
        setIsConnected(false);
        setAuthError(
          t('modals.uploadDoc.connectors.sharePoint.sessionExpired'),
        );
        setIsValidating(false);
        return false;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(
          validateData.user_email ||
            t('modals.uploadDoc.connectors.auth.connectedUser'),
        );
        setIsConnected(true);
        setAuthError('');
        setAccessToken(validateData.access_token || null);
        setIsValidating(false);

        return true;
      } else {
        setIsConnected(false);
        setAuthError(
          validateData.error ||
            t('modals.uploadDoc.connectors.sharePoint.sessionExpiredGeneric'),
        );
        setIsValidating(false);
        return false;
      }
    } catch (error) {
      console.error('Error validating session:', error);
      setAuthError(t('modals.uploadDoc.connectors.sharePoint.validateFailed'));
      setIsConnected(false);
      setIsValidating(false);
      return false;
    }
  };

  const handleDisconnect = async () => {
    const sessionToken = getSessionToken('share_point');
    if (sessionToken) {
      try {
        const apiHost = import.meta.env.VITE_API_HOST;
        await fetch(`${apiHost}/api/connectors/disconnect`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            provider: 'share_point',
            session_token: sessionToken,
          }),
        });
      } catch (err) {
        console.error('Error disconnecting from SharePoint:', err);
      }
    }

    removeSessionToken('share_point');
    setIsConnected(false);
    setAccessToken(null);
    setUserEmail('');
    setAuthError('');
  };

  const handleOpenPicker = async () => {
    alert('Feature not supported yet.');
  };

  return (
    <div>
      {isValidating ? (
        <>
          <ConnectedStateSkeleton />
          <FilesSectionSkeleton />
        </>
      ) : (
        <>
          <ConnectorAuth
            provider="share_point"
            label={t('modals.uploadDoc.connectors.sharePoint.connect')}
            onSuccess={(data) => {
              setUserEmail(
                data.user_email ||
                  t('modals.uploadDoc.connectors.auth.connectedUser'),
              );
              setIsConnected(true);
              setAuthError('');

              if (data.session_token) {
                setSessionToken('share_point', data.session_token);
                validateSession(data.session_token);
              }
            }}
            onError={(error) => {
              setAuthError(error);
              setIsConnected(false);
            }}
            isConnected={isConnected}
            userEmail={userEmail}
            onDisconnect={handleDisconnect}
            errorMessage={authError}
          />

          {isConnected && (
            <div className="rounded-lg border border-[#EEE6FF78] dark:border-[#6A6A6A]">
              <div className="p-4">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium">
                    {t('modals.uploadDoc.connectors.sharePoint.selectedFiles')}
                  </h3>
                  <button
                    onClick={() => handleOpenPicker()}
                    className="rounded-md bg-[#A076F6] px-3 py-1 text-sm text-white hover:bg-[#8A5FD4]"
                    disabled={isLoading}
                  >
                    {isLoading
                      ? t('modals.uploadDoc.connectors.sharePoint.loading')
                      : t('modals.uploadDoc.connectors.sharePoint.selectFiles')}
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default SharePointPicker;
