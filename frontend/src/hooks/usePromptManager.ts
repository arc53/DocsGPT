import { useCallback, useState, useEffect } from 'react';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Prompt } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';

type UsePromptManagerProps = {
  initialPrompts: Prompt[];
  onPromptSelect: (name: string, id: string, type: string) => void;
  onPromptsUpdate: (updatedPrompts: Prompt[]) => void;
};

type PromptContentResponse = {
  id: string;
  name: string;
  content: string;
};

type PromptCreateResponse = {
  id: string;
};

export const usePromptManager = ({
  initialPrompts,
  onPromptSelect,
  onPromptsUpdate,
}: UsePromptManagerProps) => {
  const token = useSelector(selectToken);

  const [prompts, setPrompts] = useState<Prompt[]>(initialPrompts);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPrompts(initialPrompts);
  }, [initialPrompts]);

  const handleApiCall = async <T>(
    apiCall: () => Promise<Response>,
    errorMessage: string,
  ): Promise<T | null> => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await apiCall();
      if (!response.ok) {
        const errorData = await response.text();
        console.error(`${errorMessage}: ${response.status} ${errorData}`);
        throw new Error(`${errorMessage} (Status: ${response.status})`);
      }
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        return (await response.json()) as T;
      }
      return null;
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      console.error(err);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  const addPrompt = useCallback(
    async (name: string, content: string): Promise<Prompt | null> => {
      const newPromptData = await handleApiCall<PromptCreateResponse>(
        () => userService.createPrompt({ name, content }, token),
        'Failed to add prompt',
      );

      if (newPromptData) {
        const newPrompt: Prompt = {
          name,
          id: newPromptData.id,
          type: 'private',
        };
        const updatedPrompts = [...prompts, newPrompt];
        setPrompts(updatedPrompts);
        onPromptsUpdate(updatedPrompts);
        onPromptSelect(newPrompt.name, newPrompt.id, newPrompt.type);
        return newPrompt;
      }
      return null;
    },
    [token, prompts, onPromptsUpdate, onPromptSelect],
  );

  const deletePrompt = useCallback(
    async (idToDelete: string): Promise<void> => {
      const originalPrompts = [...prompts];
      const updatedPrompts = prompts.filter(
        (prompt) => prompt.id !== idToDelete,
      );
      setPrompts(updatedPrompts);
      onPromptsUpdate(updatedPrompts);

      const result = await handleApiCall<null>(
        () => userService.deletePrompt({ id: idToDelete }, token),
        'Failed to delete prompt',
      );

      if (result === null && error) {
        setPrompts(originalPrompts);
        onPromptsUpdate(originalPrompts);
      } else {
        if (updatedPrompts.length > 0) {
          onPromptSelect(
            updatedPrompts[0].name,
            updatedPrompts[0].id,
            updatedPrompts[0].type,
          );
        }
      }
    },
    [token, prompts, onPromptsUpdate, onPromptSelect, error],
  );

  const fetchPromptContent = useCallback(
    async (id: string): Promise<string | null> => {
      const promptDetails = await handleApiCall<PromptContentResponse>(
        () => userService.getSinglePrompt(id, token),
        'Failed to fetch prompt content',
      );
      return promptDetails ? promptDetails.content : null;
    },
    [token],
  );

  const updatePrompt = useCallback(
    async (
      id: string,
      name: string,
      content: string,
      type: string,
    ): Promise<boolean> => {
      const result = await handleApiCall<{ success: boolean }>(
        () => userService.updatePrompt({ id, name, content }, token),
        'Failed to update prompt',
      );

      if (result?.success) {
        const updatedPrompts = prompts.map((p) =>
          p.id === id ? { ...p, name, type } : p,
        );
        setPrompts(updatedPrompts);
        onPromptsUpdate(updatedPrompts);
        onPromptSelect(name, id, type);
        return true;
      }
      return false;
    },
    [token, prompts, onPromptsUpdate, onPromptSelect],
  );

  return {
    prompts,
    isLoading,
    error,
    addPrompt,
    deletePrompt,
    fetchPromptContent,
    updatePrompt,
    setError,
  };
};
