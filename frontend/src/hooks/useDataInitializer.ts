import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import {
  getDocs,
  getConversations,
  getPrompts,
} from '../preferences/preferenceApi';
import {
  selectConversations,
  selectToken,
  setConversations,
  setPrompts,
  setSourceDocs,
  setSpeechAvailability,
} from '../preferences/preferenceSlice';

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
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const conversations = useSelector(selectConversations);

  // Speech features; /api/config needs no auth.
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
      })
      .catch(() => undefined);
  }, [dispatch]);

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
        dispatch(setConversations({ ...conversations, loading: true }));
        try {
          const fetchedConversations = await getConversations(token);
          dispatch(setConversations(fetchedConversations));
        } catch (error) {
          console.error('Failed to fetch conversations:', error);
          dispatch(setConversations({ data: null, loading: false }));
        }
      }
    };

    fetchConversationsData();
  }, [isAuthLoading, conversations?.data, token]);
}
