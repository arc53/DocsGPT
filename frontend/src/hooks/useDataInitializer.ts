import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import {
  loadConnectors,
  selectConnectorsEnabled,
  setConnectorsEnabled,
} from '../connectors/connectorsSlice';
import { claimLegacySessionTokens } from '../utils/providerUtils';
import {
  getDocs,
  getConversations,
  getPrompts,
} from '../preferences/preferenceApi';
import {
  selectConversations,
  selectToken,
  receiveConversations,
  setConversations,
  setConversationsLoading,
  setPrompts,
  setAttachmentBudgetShare,
  setAuthRequired,
  setSourceDocs,
  setSpeechAvailability,
} from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

/**
 * useDataInitializer Hook
 *
 * Custom hook responsible for initializing all application data on mount.
 * This hook handles:
 * - Fetching and setting up source documents
 * - Fetching and setting up prompts
 * - Fetching and setting up conversations
 * - Reading which speech features the server has switched on
 *
 * @param isAuthLoading -
 */
export default function useDataInitializer(isAuthLoading: boolean) {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const conversations = useSelector(selectConversations);

  // Speech features and the attachment budget; /api/config needs no auth.
  useEffect(() => {
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        dispatch(
          setSpeechAvailability({
            tts: config?.tts_available !== false,
            stt: config?.stt_available !== false,
          }),
        );
        dispatch(setAuthRequired(config?.requires_auth === true));
        // A backend from before connectors has no flag: hide the page.
        dispatch(setConnectorsEnabled(config?.connectors_enabled === true));
        const share = Number(config?.attachment_budget_share);
        dispatch(
          setAttachmentBudgetShare(
            Number.isFinite(share) && share > 0 ? share : null,
          ),
        );
      })
      .catch(() => undefined);
  }, [dispatch]);

  // Connections load once at start so the nav can flag one that needs
  // signing in again before any connectors page is opened.
  const connectorsEnabled = useSelector(selectConnectorsEnabled);
  useEffect(() => {
    if (isAuthLoading || !connectorsEnabled) return;
    dispatch(loadConnectors({ token }));
  }, [isAuthLoading, connectorsEnabled, token, dispatch]);

  // Connector sign-ins used to leave a session token in localStorage. Link
  // each one to its server-side connection once, then forget it.
  useEffect(() => {
    if (isAuthLoading) return;
    claimLegacySessionTokens(token);
  }, [isAuthLoading, token]);

  // Initialize documents
  useEffect(() => {
    // Skip if auth is still loading
    if (isAuthLoading) {
      return;
    }

    const fetchDocs = async () => {
      try {
        const data = await getDocs(token);
        dispatch(setSourceDocs(data));
      } catch (error) {
        console.error('Failed to fetch documents:', error);
      }
    };

    fetchDocs();
  }, [isAuthLoading, token]);

  // Initialize prompts
  useEffect(() => {
    // Skip if auth is still loading
    if (isAuthLoading) {
      return;
    }

    const fetchPromptsData = async () => {
      try {
        const data = await getPrompts(token);
        dispatch(setPrompts(data));
      } catch (error) {
        console.error('Failed to fetch prompts:', error);
      }
    };

    fetchPromptsData();
  }, [isAuthLoading, token]);

  // Initialize conversations
  useEffect(() => {
    // Skip if auth is still loading
    if (isAuthLoading) {
      return;
    }

    const fetchConversationsData = async () => {
      if (!conversations?.data) {
        dispatch(setConversationsLoading(true));
        try {
          const fetchedConversations = await getConversations(token);
          dispatch(receiveConversations(fetchedConversations));
        } catch (error) {
          console.error('Failed to fetch conversations:', error);
          dispatch(setConversations({ data: null, loading: false }));
        }
      }
    };

    fetchConversationsData();
  }, [isAuthLoading, conversations?.data, token]);
}
