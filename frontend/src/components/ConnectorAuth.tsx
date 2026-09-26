import { CircleCheck, TriangleAlert } from 'lucide-react';
import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import { isTrustedConnectorMessage } from '../utils/connectorAuthUtils';
import { Alert, AlertDescription } from './ui/alert';
import { Button } from './ui/button';

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
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const completedRef = useRef(false);
  const intervalRef = useRef<number | null>(null);
  const authWindowRef = useRef<Window | null>(null);
  // Origin the OAuth callback page is served from, as reported by the backend.
  const callbackOriginRef = useRef<string | null>(null);
  // Hold the exact listener identity so unmount cleanup removes the same fn.
  const messageHandlerRef = useRef<((event: MessageEvent) => void) | null>(
    null,
  );
  // Tracks mount status so async ``fetch`` resolves after unmount don't
  // call ``onSuccess`` / ``onError`` on a vanished parent.
  const mountedRef = useRef(true);

  const cleanup = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (messageHandlerRef.current) {
      window.removeEventListener('message', messageHandlerRef.current as any);
      messageHandlerRef.current = null;
    }
  };

  const handleAuthMessage = (event: MessageEvent) => {
    // Only the popup we opened, on the callback origin, may report a result.
    if (
      !isTrustedConnectorMessage(
        event,
        authWindowRef.current,
        callbackOriginRef.current,
      )
    ) {
      return;
    }
    const successGeneric = event.data?.type === 'connector_auth_success';
    const successProvider = event.data?.type === `${provider}_auth_success`;
    const errorProvider = event.data?.type === `${provider}_auth_error`;

    if (successGeneric || successProvider) {
      completedRef.current = true;
      cleanup();
      authWindowRef.current = null;
      onSuccess({
        session_token: event.data.session_token,
        user_email:
          event.data.user_email ||
          t('modals.uploadDoc.connectors.auth.connectedUser'),
      });
    } else if (errorProvider) {
      completedRef.current = true;
      cleanup();
      authWindowRef.current = null;
      onError(
        event.data.error || t('modals.uploadDoc.connectors.auth.authFailed'),
      );
    }
  };

  const handleAuth = () => {
    completedRef.current = false;
    // Close any popup left over from a previous click before wiping
    // the ref — otherwise the old window keeps living with no
    // interval watching it and no listener handling its messages.
    if (authWindowRef.current && !authWindowRef.current.closed) {
      authWindowRef.current.close();
    }
    authWindowRef.current = null;
    cleanup();

    // Synchronous popup inside the click; navigated below after the
    // async URL fetch resolves. Otherwise Safari blocks it as non-gesture.
    const authWindow = window.open(
      'about:blank',
      `${provider}-auth`,
      'width=500,height=600,scrollbars=yes,resizable=yes',
    );
    if (!authWindow) {
      onError(t('modals.uploadDoc.connectors.auth.popupBlocked'));
      return;
    }
    authWindowRef.current = authWindow;

    (async () => {
      try {
        const authResponse = await userService.getConnectorAuthUrl(
          provider,
          token,
        );
        if (!mountedRef.current) {
          authWindow.close();
          return;
        }

        if (!authResponse.ok) {
          authWindow.close();
          throw new Error(
            `${t('modals.uploadDoc.connectors.auth.authUrlFailed')}: ${authResponse.status}`,
          );
        }

        const authData = await authResponse.json();
        if (!mountedRef.current) {
          authWindow.close();
          return;
        }
        if (!authData.success || !authData.authorization_url) {
          authWindow.close();
          throw new Error(
            authData.error ||
              t('modals.uploadDoc.connectors.auth.authUrlFailed'),
          );
        }

        if (authWindow.closed) {
          // User closed the placeholder before we resolved.
          authWindowRef.current = null;
          onError(t('modals.uploadDoc.connectors.auth.authCancelled'));
          return;
        }
        callbackOriginRef.current = authData.callback_origin || null;
        authWindow.location.href = authData.authorization_url;

        messageHandlerRef.current = handleAuthMessage;
        window.addEventListener('message', handleAuthMessage as any);

        const checkClosed = window.setInterval(() => {
          if (authWindow.closed) {
            clearInterval(checkClosed);
            intervalRef.current = null;
            if (messageHandlerRef.current) {
              window.removeEventListener(
                'message',
                messageHandlerRef.current as any,
              );
              messageHandlerRef.current = null;
            }
            authWindowRef.current = null;
            if (!completedRef.current) {
              onError(t('modals.uploadDoc.connectors.auth.authCancelled'));
            }
          }
        }, 1000);
        intervalRef.current = checkClosed;
      } catch (error) {
        if (!authWindow.closed) {
          authWindow.close();
        }
        authWindowRef.current = null;
        if (!mountedRef.current) return;
        onError(
          error instanceof Error
            ? error.message
            : t('modals.uploadDoc.connectors.auth.authFailed'),
        );
      }
    })();
  };

  useEffect(() => {
    // Re-arm on mount; React 19 strict-mode's double-invoke would otherwise
    // leave this stuck at false from the prior cleanup, aborting later awaits.
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanup();
      if (authWindowRef.current && !authWindowRef.current.closed) {
        authWindowRef.current.close();
      }
      authWindowRef.current = null;
    };
  }, []);

  return (
    <>
      {errorMessage && (
        <Alert variant="destructive" className="mb-4">
          <TriangleAlert aria-hidden="true" />
          <AlertDescription>{errorMessage}</AlertDescription>
        </Alert>
      )}

      {isConnected ? (
        <Alert variant="success" className="mb-4">
          <CircleCheck aria-hidden="true" />
          <AlertDescription className="flex items-center justify-between">
            <span className="max-w-[500px]">
              {t('modals.uploadDoc.connectors.auth.connectedAs', {
                email: userEmail,
              })}
            </span>
            {onDisconnect && (
              <Button
                type="button"
                variant="link"
                size="xs"
                onClick={onDisconnect}
                className="-my-1 ml-2 shrink-0"
              >
                {t('modals.uploadDoc.connectors.auth.disconnect')}
              </Button>
            )}
          </AlertDescription>
        </Alert>
      ) : (
        <Button type="button" onClick={handleAuth} className="w-full">
          <svg className="size-5" viewBox="0 0 24 24">
            <path
              fill="currentColor"
              d="M6.28 3l5.72 10H24l-5.72-10H6.28zm11.44 0L12 13l5.72 10H24L18.28 3h-.56zM0 13l5.72 10h5.72L5.72 13H0z"
            />
          </svg>
          {label}
        </Button>
      )}
    </>
  );
};

export default ConnectorAuth;
