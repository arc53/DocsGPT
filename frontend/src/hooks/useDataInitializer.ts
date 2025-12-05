import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { Doc } from '../models/misc';
import { getDocs, getConversations, getPrompts } from '../preferences/preferenceApi';
import {
  selectConversations,
  selectSelectedDocs,
  selectToken,
  setConversations,
  setPrompts,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';

/**
 * useDataInitializer Hook
 *
 * Custom hook responsible for initializing all application data on mount.
 * This hook handles:
 * - Fetching and setting up documents (source docs and selected docs)
 * - Fetching and setting up prompts
 * - Fetching and setting up conversations
 *
 * @param isAuthLoading - 
 */
export default function useDataInitializer(isAuthLoading: boolean) {
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const selectedDoc = useSelector(selectSelectedDocs);
  const conversations = useSelector(selectConversations);

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

        // Auto-select default document if none selected
        if (
          !selectedDoc ||
          (Array.isArray(selectedDoc) && selectedDoc.length === 0)
        ) {
          if (Array.isArray(data)) {
            data.forEach((doc: Doc) => {
              if (doc.model && doc.name === 'default') {
                dispatch(setSelectedDocs([doc]));
              }
            });
          }
        }
      } catch (error) {
        console.error('Failed to fetch documents:', error);
      }
    };

    fetchDocs();
  }, [isAuthLoading, token, dispatch, selectedDoc]);

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
    // Only run once when auth completes
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  }, [isAuthLoading, conversations?.data, token, dispatch, conversations]);
}

