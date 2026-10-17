import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useLocation } from 'react-router-dom';

import userService from '@/api/services/userService';
import DocsGPTMark from '@/assets/logo-b.svg';
import DocsGPTMarkWhite from '@/assets/logo-w.svg';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { LoadingState } from '@/components/ui/loading-state';
import { useDarkTheme } from '@/hooks';
import { selectToken } from '@/preferences/preferenceSlice';

type Result =
  | { state: 'working' }
  | {
      state: 'connected';
      provider: string;
      connectionId: string;
      userEmail: string;
      returnOrigin?: string;
    }
  | { state: 'cancelled' }
  | { state: 'failed'; provider?: string; returnOrigin?: string };

const CLOSE_DELAY_MS = 1500;

async function finishSignIn(
  params: URLSearchParams,
  token: string | null,
): Promise<Result> {
  const error = params.get('error');
  if (error) {
    return error === 'access_denied'
      ? { state: 'cancelled' }
      : { state: 'failed' };
  }
  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) return { state: 'failed' };
  try {
    const response = await userService.completeConnectorAuth(
      { code, state },
      token,
    );
    const data = await response.json();
    if (response.ok && data.success && data.connection_id) {
      return {
        state: 'connected',
        provider: data.provider,
        connectionId: data.connection_id,
        userEmail: data.user_email,
        returnOrigin: data.return_origin,
      };
    }
    return {
      state: 'failed',
      provider: data.provider,
      returnOrigin: data.return_origin,
    };
  } catch {
    return { state: 'failed' };
  }
}

/** Tell the tab that opened the sign-in pop-up how it ended. */
function reportToOpener(result: Result): boolean {
  const opener = window.opener as Window | null;
  if (!opener || opener === window) return false;
  // Cancelling needs no message: the opener reports it when the pop-up closes.
  if (result.state === 'cancelled') return true;
  if (result.state === 'working') return false;
  const message =
    result.state === 'connected'
      ? {
          type: `${result.provider}_auth_success`,
          connection_id: result.connectionId,
          user_email: result.userEmail,
        }
      : {
          type: result.provider
            ? `${result.provider}_auth_error`
            : 'connector_auth_error',
        };
  try {
    opener.postMessage(message, result.returnOrigin || window.location.origin);
  } catch {
    return false;
  }
  return true;
}

/**
 * Where a connector's OAuth sign-in returns (`/connectors/callback`), either
 * straight from the provider or forwarded by the API callback. The page posts
 * the provider's code with this browser's own login, so only the user who
 * started the sign-in can finish it, then hands the result to the opener.
 */
export default function ConnectorCallback() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const location = useLocation();
  // Read once: the URL is cleared below, and the code is single-use.
  const [params] = useState(() => new URLSearchParams(location.search));
  const [result, setResult] = useState<Result>({ state: 'working' });
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    // Keep the code out of history and of any later Referer.
    window.history.replaceState(null, '', window.location.pathname);
    void finishSignIn(params, token).then((finished) => {
      setResult(finished);
      if (reportToOpener(finished)) {
        window.setTimeout(() => window.close(), CLOSE_DELAY_MS);
      }
    });
  }, []);

  if (result.state === 'working') return <LoadingState fill="screen" />;

  const auth = 'modals.uploadDoc.connectors.auth';
  const callback = 'modals.uploadDoc.connectors.callback';
  return (
    <main className="bg-background flex min-h-dvh flex-col items-center px-4 py-10">
      <div className="flex w-full max-w-md flex-col gap-6">
        <img
          src={isDarkTheme ? DocsGPTMarkWhite : DocsGPTMark}
          alt="DocsGPT"
          className="h-10 w-auto self-start"
        />
        {result.state === 'connected' ? (
          <Alert variant="success">
            <AlertDescription>
              {t(`${auth}.connectedAs`, {
                email: result.userEmail || t(`${auth}.connectedUser`),
                interpolation: { escapeValue: false },
              })}
            </AlertDescription>
          </Alert>
        ) : (
          <Alert
            variant={result.state === 'failed' ? 'destructive' : 'warning'}
          >
            <AlertDescription>
              {result.state === 'failed'
                ? t(`${callback}.failed`)
                : t(`${auth}.authCancelled`)}
            </AlertDescription>
          </Alert>
        )}
        <p className="text-muted-foreground text-sm">
          {t(`${callback}.closeWindow`)}{' '}
          <Button variant="link" size="inline" asChild>
            <a href="/">{t(`${callback}.backToApp`)}</a>
          </Button>
        </p>
      </div>
    </main>
  );
}
