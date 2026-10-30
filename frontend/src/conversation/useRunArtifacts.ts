import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
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
 * A 403 is no files: an unsaved draft's preview (or a workflow the caller
 * doesn't own) reports a run id with no saved run behind it.
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
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  // Scoped to the run they came from, so another run never shows them.
  const [loaded, setLoaded] = useState<{
    runId: string;
    artifacts: RunArtifactSummary[];
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setFailed(false);
    if (!workflowRunId) return;
    let cancelled = false;
    userService
      .listWorkflowRunArtifacts(workflowRunId, token)
      .then(async (response: Response) => {
        if (response.status === 403) {
          if (!cancelled) setLoaded({ runId: workflowRunId, artifacts: [] });
          return;
        }
        if (!response.ok) throw new Error('list failed');
        const data = await response.json();
        if (cancelled) return;
        if (!data?.success) throw new Error('list failed');
        setLoaded({
          runId: workflowRunId,
          artifacts: (data.artifacts ?? []) as RunArtifactSummary[],
        });
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowRunId, token, inProgress, attempt]);

  const artifacts =
    workflowRunId && loaded?.runId === workflowRunId ? loaded.artifacts : null;
  const items = useMemo(
    () =>
      artifacts
        ? // The list is newest first; cards go in the order produced.
          cardsFromRunArtifacts(artifacts, (id) =>
            t('agents.workflow.artifacts.untitled', { id }),
          ).reverse()
        : [],
    [artifacts, t],
  );
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { items, failed, retry };
}
