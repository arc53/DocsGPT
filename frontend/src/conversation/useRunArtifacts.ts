import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { selectToken } from '../preferences/preferenceSlice';
import {
  cardsFromRunArtifacts,
  type ArtifactCardItem,
  type RunArtifactSummary,
} from './artifactCards';

/**
 * A workflow run's artifacts as cards. Every workflow answer carries a run
 * id but few runs make artifacts, so it stays empty (no spinner) until the
 * list arrives; it refetches when the run stops streaming, so a run's last
 * files show once it ends.
 *
 * Args:
 *   workflowRunId: The run; nothing is fetched without one.
 *   inProgress: True while the run's answer is streaming.
 *
 * Returns:
 *   `items`, `failed` when the list could not load, and `retry`.
 */
export function useRunArtifacts(
  workflowRunId: string | undefined,
  inProgress = false,
): { items: ArtifactCardItem[]; failed: boolean; retry: () => void } {
  const token = useSelector(selectToken);
  const [items, setItems] = useState<ArtifactCardItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!workflowRunId) {
      setItems([]);
      setFailed(false);
      return;
    }
    let cancelled = false;
    setFailed(false);
    userService
      .listWorkflowRunArtifacts(workflowRunId, token)
      .then(async (response: Response) => {
        if (!response.ok) throw new Error('list failed');
        const data = await response.json();
        if (cancelled) return;
        if (!data?.success) throw new Error('list failed');
        // The list is newest first; cards go in the order produced.
        setItems(
          cardsFromRunArtifacts(
            (data.artifacts ?? []) as RunArtifactSummary[],
          ).reverse(),
        );
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowRunId, token, inProgress, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { items, failed, retry };
}
