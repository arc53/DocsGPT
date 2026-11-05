import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import {
  loadConnectors,
  selectConnectorsEnabled,
  setConnectorsEnabled,
} from '../connectors/connectorsSlice';
import { initChatPrompt } from '../preferences/chatPrompt';
import { claimLegacySessionTokens } from '../utils/providerUtils';
import { getDocs, getConversations } from '../preferences/preferenceApi';
import {
  selectConversations,
  selectToken,
  receiveConversations,
  setConversationsLoading,
  setAnalyticsAvailability,
  setAttachmentBudgetShare,
  setAuthRequired,
  setSourceDocs,
  setSpeechAvailability,
} from '../preferences/preferenceSlice';
import { analyticsAvailability } from '../settings/insights/useAnalyticsAvailability';
import type { AppDispatch } from '../store';

/**
 * useDataInitializer Hook
 *
 * Custom hook responsible for initializing all application data on mount.
 * This hook handles:
 * - Fetching and setting up source documents
 * - Fetching and setting up prompts, and the chat prompt the server keeps
 * - Fetching and setting up conversations
 * - Reading which speech features the server has switched on, and whether
 *   conversation insights are, with the insights editor's limits
 *
 * @param isAuthLoading - Auth is still resolving; nothing loads until it is done.
 * @param authType - The server's auth mode (`none`, `simple_jwt`, …), once known.
 */
export default function useDataInitializer(
  isAuthLoading: boolean,
  authType?: string | null,
) {
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
        dispatch(setAnalyticsAvailability(analyticsAvailability(config)));
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

  // Initialize prompts and the one chats use. A mode that needs a token
  // and has none (the sign-in is still to come) asks the server nothing
  // about the user and keeps default.
  const signedOut = !token && !!authType && authType !== 'none';
  useEffect(() => {
    // Skip if auth is still loading
    if (isAuthLoading) {
      return;
    }

    // The server's chat prompt applies as soon as it answers (asked again
    // if it couldn't); the prompt list names it when it arrives. A renewed
    // token runs this again; a pick the same user made meanwhile stands.
    let cancelled = false;
    dispatch(
      initChatPrompt(token, { signedOut, cancelled: () => cancelled }),
    ).catch((error: unknown) =>
      console.error('Failed to fetch prompts:', error),
    );
    return () => {
      cancelled = true;
    };
  }, [isAuthLoading, token, signedOut]);

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
          dispatch(receiveConversations({ data: null, loading: false }));
        }
      }
    };

    fetchConversationsData();
  }, [isAuthLoading, conversations?.data, token]);
}
