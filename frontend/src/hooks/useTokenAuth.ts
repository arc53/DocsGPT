import { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { baseURL } from '../api/client';
import endpoints from '../api/endpoints';
import userService from '../api/services/userService';
import {
  clearRoles,
  selectToken,
  setRoles,
  setToken,
} from '../preferences/preferenceSlice';
import {
  decodeJwtPayload,
  getJwtRemainingMs,
  isJwtExpired,
} from '../utils/jwtUtils';

const OIDC_ATTEMPT_KEY = 'oidc_login_attempted';
const OIDC_RETURN_TO_KEY = 'oidc_return_to';

// Renew the OIDC session when less than this much lifetime remains.
const OIDC_RENEWAL_THRESHOLD_MS = 15 * 60 * 1000;
// Delay before retrying a renewal that failed transiently (network/503).
const OIDC_RENEWAL_RETRY_MS = 60 * 1000;
// setTimeout treats delays above 2^31 - 1 ms as 0 — clamp to avoid firing
// immediately for far-future expiries.
const MAX_TIMER_DELAY_MS = 2 ** 31 - 1;

// Module-level so the two hook instances (AuthWrapper + Navigation) and
// StrictMode's double-invoked effects share one exchange/redirect — the
// handoff code is single-use server-side, so a second POST would fail.
let oidcExchangePromise: Promise<string | null> | null = null;
let oidcRedirectStarted = false;

// Renewal state is module-level for the same reason: at most one renewal
// timer and one in-flight refresh may exist app-wide, because the server
// rotates the refresh token on every renewal — concurrent renewals would
// invalidate each other.
let oidcRenewalTimer: ReturnType<typeof setTimeout> | null = null;
let oidcRenewalPromise: Promise<void> | null = null;
// Set when the server reports 404 no_refresh_token: the IdP issued no
// refresh token for this session, so silent renewal is impossible until a
// new token is stored. Expiry then falls back to the redirect-login path,
// which re-authenticates silently while the IdP session is still alive.
let oidcRenewalUnavailable = false;

// Dedupe the /api/user/me fetch across the two hook instances (AuthWrapper +
// Navigation) and StrictMode's double-invoked effects, keyed by the active
// token. A failed fetch clears the cache so a later run can retry; a successful
// one stays cached for that token.
let meFetchKey: string | null = null;
let meFetchPromise: Promise<string[] | null> | null = null;

export function fetchMeRoles(token: string | null): Promise<string[] | null> {
  const key = token ?? '__anon__';
  if (meFetchKey === key && meFetchPromise) return meFetchPromise;
  meFetchKey = key;
  const promise = (async () => {
    try {
      const response = await userService.getMe(token);
      if (!response.ok) return null;
      const data = await response.json();
      return Array.isArray(data.roles) ? data.roles : [];
    } catch {
      return null;
    }
  })();
  meFetchPromise = promise;
  promise.then((roles) => {
    if (roles === null && meFetchPromise === promise) {
      meFetchKey = null;
      meFetchPromise = null;
    }
  });
  return promise;
}

const claimString = (value: unknown): string | undefined =>
  typeof value === 'string' && value !== '' ? value : undefined;

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
  const [oidcErrorCode, setOidcErrorCode] = useState<string | null>(null);
  const [oidcProviderName, setOidcProviderName] = useState<string | null>(null);
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
        // A fresh session may carry a refresh token even if the previous
        // one did not.
        oidcRenewalUnavailable = false;
        localStorage.setItem('authToken', newToken);
        setOidcErrorCode(null);
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
      const errorCode = decodeURIComponent(hash.slice('#oidc_error='.length));
      console.error('OIDC login failed:', errorCode);
      setOidcErrorCode(errorCode);
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
          setOidcProviderName(config.oidc?.provider_name ?? null);
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

  useEffect(() => {
    // Silent session renewal: refresh the OIDC session JWT shortly before
    // it expires so users never hit a mid-session login redirect. Re-runs
    // on every token change, which is what reschedules the timer after a
    // successful renewal.
    if (authType !== 'oidc') return;
    const remaining = token ? getJwtRemainingMs(token) : null;
    if (
      !token ||
      remaining === null ||
      isJwtExpired(token) ||
      oidcRenewalUnavailable
    ) {
      // No renewable session (initializeAuth owns expired-token recovery)
      // — drop any pending renewal/retry timer.
      if (oidcRenewalTimer !== null) {
        clearTimeout(oidcRenewalTimer);
        oidcRenewalTimer = null;
      }
      return;
    }

    const scheduleRetry = () => {
      if (oidcRenewalTimer !== null) clearTimeout(oidcRenewalTimer);
      oidcRenewalTimer = setTimeout(renew, OIDC_RENEWAL_RETRY_MS);
    };

    const renew = () => {
      if (oidcRenewalPromise) return; // single renewal in flight app-wide
      oidcRenewalPromise = (async () => {
        try {
          // Another tab may have renewed first — its rotation invalidated
          // our refresh token, so adopt the stored session instead of
          // making a doomed network call.
          const stored = localStorage.getItem('authToken');
          if (stored !== token) {
            dispatch(setToken(stored));
            return;
          }
          const response = await userService.refreshOidcSession(token);
          if (response.ok) {
            const { token: newToken } = await response.json();
            if (!newToken) {
              scheduleRetry();
              return;
            }
            oidcRenewalUnavailable = false;
            localStorage.setItem('authToken', newToken);
            // The token-keyed effect re-runs and schedules the next one.
            dispatch(setToken(newToken));
            return;
          }
          if (response.status === 404) {
            // no_refresh_token: stop scheduling for this session.
            oidcRenewalUnavailable = true;
            return;
          }
          if (response.status === 401) {
            // Session unusable (expired/revoked/disabled) — drop the
            // token so initializeAuth walks through a fresh login.
            localStorage.removeItem('authToken');
            dispatch(setToken(null));
            return;
          }
          // 503 or unexpected status: transient — retry once in a minute.
          scheduleRetry();
        } catch {
          scheduleRetry(); // network error: transient
        } finally {
          oidcRenewalPromise = null;
        }
      })();
    };

    // One timer app-wide: replace whatever an earlier run (or the other
    // hook instance) scheduled. A zero delay renews immediately.
    if (oidcRenewalTimer !== null) clearTimeout(oidcRenewalTimer);
    const delay = Math.min(
      Math.max(remaining - OIDC_RENEWAL_THRESHOLD_MS, 0),
      MAX_TIMER_DELAY_MS,
    );
    const timer = setTimeout(renew, delay);
    oidcRenewalTimer = timer;
    return () => {
      // Clear only the timer this effect run set — another instance may
      // have replaced it with its own since.
      if (oidcRenewalTimer === timer) {
        clearTimeout(timer);
        oidcRenewalTimer = null;
      }
    };
  }, [authType, token, dispatch]);

  useEffect(() => {
    // Resolve RBAC roles from the server once auth has settled. Roles are
    // DB-authoritative and mode-agnostic — even no-auth ('local') can be admin
    // via LOCAL_MODE_ADMIN — so /me is fetched whenever we're authenticated (or
    // running token-less in no-auth mode), and cleared while a login is pending.
    if (isAuthLoading) return; // auth still resolving — leave roles unresolved
    if (oidcFailed || showTokenModal) {
      dispatch(clearRoles());
      return;
    }
    // Token-required modes that don't have a token yet: stay unresolved.
    if (authType && authType !== 'none' && !token) {
      dispatch(clearRoles());
      return;
    }
    let cancelled = false;
    fetchMeRoles(token).then((roles) => {
      if (!cancelled) dispatch(setRoles(roles ?? []));
    });
    return () => {
      cancelled = true;
    };
  }, [authType, token, isAuthLoading, oidcFailed, showTokenModal, dispatch]);

  const handleTokenSubmit = (enteredToken: string) => {
    localStorage.setItem('authToken', enteredToken);
    dispatch(setToken(enteredToken));
    setShowTokenModal(false);
  };

  const retryOidcLogin = () => {
    sessionStorage.removeItem(OIDC_ATTEMPT_KEY);
    setOidcErrorCode(null);
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

  const oidcClaims =
    authType === 'oidc' && token ? decodeJwtPayload(token) : null;
  const userEmail = claimString(oidcClaims?.email);
  const userName = claimString(oidcClaims?.name);
  const userPicture = claimString(oidcClaims?.picture);

  return {
    authType,
    showTokenModal,
    isAuthLoading,
    token,
    handleTokenSubmit,
    oidcFailed,
    oidcErrorCode,
    oidcProviderName,
    retryOidcLogin,
    logout,
    userEmail,
    userName,
    userPicture,
  };
}
