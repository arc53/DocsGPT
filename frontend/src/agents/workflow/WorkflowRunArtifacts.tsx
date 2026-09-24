import { ChevronLeft, FileBox } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import DocumentArtifactView from '../../components/DocumentArtifactView';
import Spinner from '../../components/Spinner';
import {
  isDocumentArtifact,
  type DocumentArtifact,
} from '../../components/artifactViewUtils';
import { Button } from '@/components/ui/button';
import { selectToken } from '../../preferences/preferenceSlice';

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
            setError('Failed to load artifacts');
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
        setError('Failed to load artifacts');
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
            setDetailError('Failed to load artifact');
            setDetailLoading(false);
            return;
          }
          const data = await res.json().catch(() => null);
          if (cancelled) return;
          if (data?.success && isDocumentArtifact(data.artifact)) {
            setDetail(data.artifact);
            setDetailLoading(false);
          } else {
            setDetailError('This artifact cannot be previewed');
            setDetailLoading(false);
          }
        })
        .catch(() => {
          if (cancelled) return;
          setDetailError('Failed to load artifact');
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
      <div className="text-muted-foreground flex items-center gap-2 px-3 py-4 text-sm">
        <Spinner size="small" /> Loading artifacts...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-destructive flex items-center justify-between gap-2 px-3 py-3 text-sm">
        <span>{error}</span>
        <Button type="button" variant="outline" size="sm" onClick={loadList}>
          Retry
        </Button>
      </div>
    );
  }

  if (!artifacts || artifacts.length === 0) {
    return (
      <div className="text-muted-foreground px-3 py-3 text-sm">
        {inProgress
          ? 'Run in progress — artifacts appear here as nodes produce them.'
          : 'No artifacts produced by this run.'}
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
            <ChevronLeft className="h-4 w-4" />
            Back to artifacts
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          {detailLoading ? (
            <div className="flex h-full items-center justify-center">
              <Spinner />
            </div>
          ) : detailError ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-destructive text-sm">{detailError}</p>
            </div>
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
            <FileBox className="text-muted-foreground h-4 w-4 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="text-foreground truncate text-sm font-medium">
                {artifact.title || `Artifact ${artifact.id.slice(0, 8)}`}
              </div>
              <div className="text-muted-foreground truncate text-xs">
                {artifact.kind || 'file'}
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
