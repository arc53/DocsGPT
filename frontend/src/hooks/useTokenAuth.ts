import { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import { selectToken, setToken } from '../preferences/preferenceSlice';
import { decodeJwtPayload, isJwtExpired } from '../utils/jwtUtils';

const OIDC_ATTEMPT_KEY = 'oidc_login_attempted';
const OIDC_RETURN_TO_KEY = 'oidc_return_to';

// Module-level so the two hook instances (AuthWrapper + Navigation) and
// StrictMode's double-invoked effects share one exchange/redirect — the
// handoff code is single-use server-side, so a second POST would fail.
let oidcExchangePromise: Promise<string | null> | null = null;
let oidcRedirectStarted = false;

function exchangeOidcCodeOnce(code: string): Promise<string | null> {
  if (!oidcExchangePromise) {
    oidcExchangePromise = (async () => {
      try {
        const response = await userService.exchangeOidcCode(code);
        if (!response.ok) return null;
        const { token: newToken } = await response.json();
        return newToken ?? null;
      } catch {
        return null;
      }
    })();
  }
  return oidcExchangePromise;
}

function redirectToOidcLogin() {
  sessionStorage.setItem(OIDC_ATTEMPT_KEY, '1');
  sessionStorage.setItem(
    OIDC_RETURN_TO_KEY,
    window.location.pathname + window.location.search,
  );
  oidcRedirectStarted = true;
  window.location.replace(`${baseURL}${endpoints.USER.OIDC_LOGIN}`);
}

export default function useAuth() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [authType, setAuthType] = useState(null);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [isAuthLoading, setIsAuthLoading] = useState(true);
  const [oidcFailed, setOidcFailed] = useState(false);
  const isGeneratingToken = useRef(false);

  const generateNewToken = async () => {
    if (isGeneratingToken.current) return;
    isGeneratingToken.current = true;
    try {
      const response = await userService.getNewToken();
      const { token: newToken } = await response.json();
      localStorage.setItem('authToken', newToken);
      dispatch(setToken(newToken));
      setIsAuthLoading(false);
      return newToken;
    } finally {
      // Reset so a subsequent ``setToken(null)`` (SSE 401 recovery)
      // can trigger another generation. Without this the in-flight
      // guard would latch true forever after the first call.
      isGeneratingToken.current = false;
    }
  };

  const stripUrlFragment = () => {
    window.history.replaceState(
      null,
      '',
      window.location.pathname + window.location.search,
    );
  };

  const handleOidcAuth = async () => {
    const hash = window.location.hash;
    if (hash.startsWith('#oidc_code=')) {
      const code = hash.slice('#oidc_code='.length);
      const newToken = await exchangeOidcCodeOnce(code);
      if (newToken) {
        localStorage.setItem('authToken', newToken);
        sessionStorage.removeItem(OIDC_ATTEMPT_KEY);
        const returnTo = sessionStorage.getItem(OIDC_RETURN_TO_KEY);
        sessionStorage.removeItem(OIDC_RETURN_TO_KEY);
        if (returnTo && returnTo !== '/') {
          // Full reload: React Router doesn't observe history.replaceState,
          // so this is the simplest way back to the pre-login deep link.
          window.location.replace(returnTo);
          return;
        }
        stripUrlFragment();
        dispatch(setToken(newToken)); // effect re-runs and finishes loading
        return;
      }
      stripUrlFragment();
      setOidcFailed(true);
      setIsAuthLoading(false);
      return;
    }
    if (hash.startsWith('#oidc_error=')) {
      console.error(
        'OIDC login failed:',
        decodeURIComponent(hash.slice('#oidc_error='.length)),
      );
      stripUrlFragment();
      setOidcFailed(true);
      setIsAuthLoading(false);
      return;
    }
    if (!token || isJwtExpired(token)) {
      if (token) {
        localStorage.removeItem('authToken');
      }
      if (oidcRedirectStarted) return; // navigation underway — keep spinner
      if (sessionStorage.getItem(OIDC_ATTEMPT_KEY)) {
        // Already round-tripped to the IdP once without obtaining a
        // session — show the retry screen instead of redirect-looping.
        setOidcFailed(true);
        setIsAuthLoading(false);
        return;
      }
      redirectToOidcLogin();
      return;
    }
    setIsAuthLoading(false);
  };

  useEffect(() => {
    // Re-fires when ``token`` flips to null mid-session (e.g.
    // ``useEventStream`` dispatches ``setToken(null)`` after repeated
    // SSE 401s) so ``session_jwt`` users get a fresh token without a
    // hard reload. ``authType`` short-circuits on subsequent runs.
    const initializeAuth = async () => {
      try {
        let resolvedAuthType = authType;
        if (resolvedAuthType === null) {
          const configRes = await userService.getConfig();
          const config = await configRes.json();
          resolvedAuthType = config.auth_type;
          setAuthType(resolvedAuthType);
        }

        if (resolvedAuthType === 'oidc') {
          await handleOidcAuth();
        } else if (resolvedAuthType === 'session_jwt' && !token) {
          await generateNewToken();
        } else if (resolvedAuthType === 'simple_jwt' && !token) {
          setShowTokenModal(true);
          setIsAuthLoading(false);
        } else {
          setIsAuthLoading(false);
        }
      } catch (error) {
        console.error('Auth initialization failed:', error);
        setIsAuthLoading(false);
      }
    };
    initializeAuth();
  }, [token, authType]);

  const handleTokenSubmit = (enteredToken: string) => {
    localStorage.setItem('authToken', enteredToken);
    dispatch(setToken(enteredToken));
    setShowTokenModal(false);
  };

  const retryOidcLogin = () => {
    sessionStorage.removeItem(OIDC_ATTEMPT_KEY);
    setOidcFailed(false);
    setIsAuthLoading(true);
    redirectToOidcLogin();
  };

  const logout = () => {
    localStorage.removeItem('authToken');
    sessionStorage.removeItem(OIDC_ATTEMPT_KEY);
    sessionStorage.removeItem(OIDC_RETURN_TO_KEY);
    // Ends the IdP session too; the IdP redirects back to the app, which
    // then walks through a fresh login.
    window.location.href = `${baseURL}${endpoints.USER.OIDC_LOGOUT}`;
  };

  const userEmail =
    authType === 'oidc' && token
      ? (decodeJwtPayload(token)?.email as string | undefined)
      : undefined;

  return {
    authType,
    showTokenModal,
    isAuthLoading,
    token,
    handleTokenSubmit,
    oidcFailed,
    retryOidcLogin,
    logout,
    userEmail,
  };
}
