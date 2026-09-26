import { ChevronLeft, FileBox } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import DocumentArtifactView from '../../components/DocumentArtifactView';
import { EmptyState } from '@/components/ui/empty-state';
import { LoadingState } from '@/components/ui/loading-state';
import {
  isDocumentArtifact,
  type DocumentArtifact,
} from '../../components/artifactViewUtils';
import { Button } from '@/components/ui/button';
import { selectToken } from '../../preferences/preferenceSlice';

// Error states hold locale keys; the render translates them.
const PREVIEW_UNSUPPORTED = 'agents.workflow.artifacts.previewUnsupported';
const LIST_FAILED = 'agents.workflow.artifacts.loadListFailed';
const DETAIL_FAILED = 'agents.workflow.artifacts.loadFailed';

interface RunArtifactSummary {
  id: string;
  kind: string | null;
  title: string | null;
  current_version: number | null;
}

interface WorkflowRunArtifactsProps {
  workflowRunId: string;
  /** True while the run is still streaming; flipping to false refetches so
   * a panel opened mid-run picks up the final artifact list. */
  inProgress?: boolean;
}

/** List a workflow run's produced artifacts, with click-through preview + download. */
export default function WorkflowRunArtifacts({
  workflowRunId,
  inProgress = false,
}: WorkflowRunArtifactsProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [artifacts, setArtifacts] = useState<RunArtifactSummary[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [detail, setDetail] = useState<DocumentArtifact | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadList = useCallback(() => {
    if (!workflowRunId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    userService
      .listWorkflowRunArtifacts(workflowRunId, token)
      .then(async (res: Response) => {
        if (cancelled) return;
        if (!res.ok) {
          // A 403 is the expected unsaved-draft / unauthorized case (no
          // persisted run row): show the informational empty state. Any other
          // non-OK status (500, an expired 401, ...) is a real failure — surface
          // an error + Retry instead of masquerading as "no artifacts".
          if (res.status === 403) {
            setArtifacts([]);
          } else {
            setError(LIST_FAILED);
          }
          setLoading(false);
          return;
        }
        const data = await res.json().catch(() => null);
        if (cancelled) return;
        setArtifacts(data?.success ? (data.artifacts ?? []) : []);
        setLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        setError(LIST_FAILED);
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [workflowRunId, token]);

  useEffect(() => {
    const cleanup = loadList();
    return cleanup;
  }, [loadList, inProgress]);

  const fetchDetail = useCallback(
    (artifactId: string) => {
      let cancelled = false;
      setDetailLoading(true);
      setDetailError(null);
      userService
        .getDocumentArtifact(artifactId, token)
        .then(async (res: Response) => {
          if (cancelled) return;
          if (!res.ok) {
            setDetailError(DETAIL_FAILED);
            setDetailLoading(false);
            return;
          }
          const data = await res.json().catch(() => null);
          if (cancelled) return;
          if (data?.success && isDocumentArtifact(data.artifact)) {
            setDetail(data.artifact);
            setDetailLoading(false);
          } else {
            setDetailError(PREVIEW_UNSUPPORTED);
            setDetailLoading(false);
          }
        })
        .catch(() => {
          if (cancelled) return;
          setDetailError(DETAIL_FAILED);
          setDetailLoading(false);
        });
      return () => {
        cancelled = true;
      };
    },
    [token],
  );

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    const cleanup = fetchDetail(selectedId);
    return cleanup;
  }, [selectedId, fetchDetail]);

  if (loading) {
    return (
      <LoadingState
        fill="block"
        size="sm"
        label={t('agents.workflow.artifacts.loading')}
      />
    );
  }

  if (error) {
    return (
      <EmptyState
        tone="destructive"
        size="sm"
        illustration="none"
        title={t(error)}
        action={
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => loadList()}
          >
            {t('retry')}
          </Button>
        }
      />
    );
  }

  if (!artifacts || artifacts.length === 0) {
    return (
      <div className="text-muted-foreground px-3 py-3 text-sm">
        {inProgress
          ? t('agents.workflow.artifacts.inProgress')
          : t('agents.workflow.artifacts.empty')}
      </div>
    );
  }

  if (selectedId) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="mb-2 flex items-center">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setSelectedId(null)}
          >
            <ChevronLeft />
            {t('agents.workflow.artifacts.back')}
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          {detailLoading ? (
            <LoadingState fill="parent" />
          ) : detailError === PREVIEW_UNSUPPORTED ? (
            // Not a failed load: nothing to retry.
            <EmptyState
              size="sm"
              illustration="none"
              title={t(detailError)}
              className="h-full"
            />
          ) : detailError ? (
            <EmptyState
              tone="destructive"
              size="sm"
              illustration="none"
              title={t(detailError)}
              className="h-full"
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => fetchDetail(selectedId)}
                >
                  {t('retry')}
                </Button>
              }
            />
          ) : detail ? (
            <DocumentArtifactView
              artifact={detail}
              onRefresh={() => fetchDetail(selectedId)}
            />
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <ul className="space-y-2">
      {artifacts.map((artifact) => (
        <li key={artifact.id}>
          <Button
            type="button"
            variant="outline"
            onClick={() => setSelectedId(artifact.id)}
            className="h-auto w-full justify-start text-left"
          >
            <FileBox className="text-muted-foreground shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-foreground truncate text-sm font-medium">
                {artifact.title ||
                  t('agents.workflow.artifacts.untitled', {
                    id: artifact.id.slice(0, 8),
                  })}
              </div>
              <div className="text-muted-foreground truncate text-xs">
                {artifact.kind || t('agents.workflow.artifacts.fileKind')}
                {artifact.current_version != null
                  ? ` · v${artifact.current_version}`
                  : ''}
              </div>
            </div>
          </Button>
        </li>
      ))}
    </ul>
  );
}
