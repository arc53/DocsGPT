import { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken, setToken } from '../preferences/preferenceSlice';

export default function useAuth() {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [authType, setAuthType] = useState(null);
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [isAuthLoading, setIsAuthLoading] = useState(true);
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

        if (resolvedAuthType === 'session_jwt' && !token) {
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
  return { authType, showTokenModal, isAuthLoading, token, handleTokenSubmit };
}
