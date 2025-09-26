import React, { useRef } from 'react';
import { useSelector } from 'react-redux';
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';

interface ConnectorAuthProps {
  provider: string;
  onSuccess: (data: { session_token: string; user_email: string }) => void;
  onError: (error: string) => void;
  label?: string;
  isConnected?: boolean;
  userEmail?: string;
  onDisconnect?: () => void;
  errorMessage?: string;
}

const ConnectorAuth: React.FC<ConnectorAuthProps> = ({
  provider,
  onSuccess,
  onError,
  label,
  isConnected = false,
  userEmail = '',
  onDisconnect,
  errorMessage,
}) => {
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
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
    const successProvider = event.data?.type === `${provider}_auth_success`;
    const errorProvider = event.data?.type === `${provider}_auth_error`;

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

  return (
    <>
      {errorMessage && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#E60000] dark:border-[#D42626] bg-transparent dark:bg-[#D426261A] p-2">
          <svg width="30" height="30" viewBox="0 0 30 30" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M7.09974 24.5422H22.9C24.5156 24.5422 25.5228 22.7901 24.715 21.3947L16.8149 7.74526C16.007 6.34989 13.9927 6.34989 13.1848 7.74526L5.28471 21.3947C4.47686 22.7901 5.48405 24.5422 7.09974 24.5422ZM14.9998 17.1981C14.4228 17.1981 13.9507 16.726 13.9507 16.149V14.0507C13.9507 13.4736 14.4228 13.0015 14.9998 13.0015C15.5769 13.0015 16.049 13.4736 16.049 14.0507V16.149C16.049 16.726 15.5769 17.1981 14.9998 17.1981ZM16.049 21.3947H13.9507V19.2964H16.049V21.3947Z" fill={isDarkTheme ? '#EECF56' : '#E60000'} />
          </svg>

          <span className='text-[#E60000] dark:text-[#E37064] text-sm' style={{
            fontFamily: 'Inter',
            lineHeight: '100%'
          }}>
            {errorMessage}
          </span>
        </div>
      )}

      {isConnected ? (
        <div className="mb-4">
          <div className="w-full flex items-center justify-between rounded-[10px] bg-[#8FDD51] px-4 py-2 text-[#212121] font-medium text-sm">
            <div className="flex items-center gap-2">
              <svg className="h-4 w-4" viewBox="0 0 24 24">
                <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
              </svg>
              <span>Connected as {userEmail}</span>
            </div>
            {onDisconnect && (
              <button
                onClick={onDisconnect}
                className="text-[#212121] hover:text-gray-700 font-medium text-xs underline"
              >
                Disconnect
              </button>
            )}
          </div>
        </div>
      ) : (
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
          {label}
        </button>
      )}
    </>
  );
};

export default ConnectorAuth;