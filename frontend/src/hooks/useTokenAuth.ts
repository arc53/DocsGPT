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
    const response = await userService.getNewToken();
    const { token: newToken } = await response.json();
    localStorage.setItem('authToken', newToken);
    dispatch(setToken(newToken));
    setIsAuthLoading(false);
    return newToken;
  };

  useEffect(() => {
    const initializeAuth = async () => {
      try {
        const configRes = await userService.getConfig();
        const config = await configRes.json();
        setAuthType(config.auth_type);

        if (config.auth_type === 'session_jwt' && !token) {
          await generateNewToken();
        } else if (config.auth_type === 'simple_jwt' && !token) {
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
  }, []);

  const handleTokenSubmit = (enteredToken: string) => {
    localStorage.setItem('authToken', enteredToken);
    dispatch(setToken(enteredToken));
    setShowTokenModal(false);
  };
  return { authType, showTokenModal, isAuthLoading, token, handleTokenSubmit };
}
