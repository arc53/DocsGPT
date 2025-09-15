import React, { useRef } from 'react';
import { useSelector } from 'react-redux';
import { selectToken } from '../preferences/preferenceSlice';

interface ConnectorAuthProps {
  provider: string;
  onSuccess: (data: { session_token: string; user_email: string }) => void;
  onError: (error: string) => void;
  label?: string;
}

const providerLabel = (provider: string) => {
  const map: Record<string, string> = {
    google_drive: 'Google Drive',
  };
  return map[provider] || provider.replace(/_/g, ' ');
};

const ConnectorAuth: React.FC<ConnectorAuthProps> = ({
  provider,
  onSuccess,
  onError,
  label,
}) => {
  const token = useSelector(selectToken);
  const completedRef = useRef(false);
  const intervalRef = useRef<number | null>(null);

  const cleanup = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    window.removeEventListener('message', handleAuthMessage as any);
  };

  const handleAuthMessage = (event: MessageEvent) => {
    const successGeneric = event.data?.type === 'connector_auth_success';
    const successProvider =
      event.data?.type === `${provider}_auth_success` ||
      event.data?.type === 'google_drive_auth_success';
    const errorProvider =
      event.data?.type === `${provider}_auth_error` ||
      event.data?.type === 'google_drive_auth_error';

    if (successGeneric || successProvider) {
      completedRef.current = true;
      cleanup();
      onSuccess({
        session_token: event.data.session_token,
        user_email: event.data.user_email || 'Connected User',
      });
    } else if (errorProvider) {
      completedRef.current = true;
      cleanup();
      onError(event.data.error || 'Authentication failed');
    }
  };

  const handleAuth = async () => {
    try {
      completedRef.current = false;
      cleanup();

      const apiHost = import.meta.env.VITE_API_HOST;
      const authResponse = await fetch(
        `${apiHost}/api/connectors/auth?provider=${provider}`,
        {
          headers: { Authorization: `Bearer ${token}` },
        },
      );

      if (!authResponse.ok) {
        throw new Error(
          `Failed to get authorization URL: ${authResponse.status}`,
        );
      }

      const authData = await authResponse.json();
      if (!authData.success || !authData.authorization_url) {
        throw new Error(authData.error || 'Failed to get authorization URL');
      }

      const authWindow = window.open(
        authData.authorization_url,
        `${provider}-auth`,
        'width=500,height=600,scrollbars=yes,resizable=yes',
      );
      if (!authWindow) {
        throw new Error(
          'Failed to open authentication window. Please allow popups.',
        );
      }

      window.addEventListener('message', handleAuthMessage as any);

      const checkClosed = window.setInterval(() => {
        if (authWindow.closed) {
          clearInterval(checkClosed);
          window.removeEventListener('message', handleAuthMessage as any);
          if (!completedRef.current) {
            onError('Authentication was cancelled');
          }
        }
      }, 1000);
      intervalRef.current = checkClosed;
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Authentication failed');
    }
  };

  const buttonLabel = label || `Connect ${providerLabel(provider)}`;

  return (
    <button
      onClick={handleAuth}
      className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-500 px-4 py-3 text-white transition-colors hover:bg-blue-600"
    >
      <svg className="h-5 w-5" viewBox="0 0 24 24">
        <path
          fill="currentColor"
          d="M6.28 3l5.72 10H24l-5.72-10H6.28zm11.44 0L12 13l5.72 10H24L18.28 3h-.56zM0 13l5.72 10h5.72L5.72 13H0z"
        />
      </svg>
      {buttonLabel}
    </button>
  );
};

export default ConnectorAuth;
