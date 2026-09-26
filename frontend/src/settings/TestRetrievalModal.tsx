import { CircleAlert, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { cn } from '../lib/utils';
import { ActiveState, Doc } from '../models/misc';
import type { Model } from '../models/types';
import { selectToken } from '../preferences/preferenceSlice';

import RetrievalOptions, {
  configToOptions,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from './components/RetrievalOptions';

/** One retrieved chunk as returned by POST /api/sources/<id>/search. */
export type RetrievedChunk = {
  rank: number;
  text: string;
  title: string | null;
  filename: string | null;
  source: string | null;
  tokens: number;
  // null when the retriever/store produces no comparable score (graphrag's PPR
  // ranking, stores without a score seam).
  score: number | null;
  score_kind: 'cosine_similarity' | 'l2_distance' | 'rrf' | null;
};

type RetrievalResult = {
  query: string;
  retriever: string;
  // The config the run actually used, echoed back by the backend.
  retrieval: { score_threshold: number | null };
  total: number;
  latency_ms: number;
  chunks: RetrievedChunk[];
};

interface TestRetrievalModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  document: Doc | null;
  hybridAvailable?: boolean;
  graphRAGAvailable?: boolean;
  availableModels?: Model[];
}

/**
 * Renders a chunk's score with the label its kind earns. The kinds are NOT
 * interchangeable: cosine similarity is higher-is-better in [0,1] and is what
 * `score_threshold` is compared against; an L2 distance (FAISS) is
 * lower-is-better and unbounded; an RRF score only ranks hits against each
 * other. Showing a bare number would invite the user to read one as another.
 */
export function ScoreBadge({ chunk }: { chunk: RetrievedChunk }) {
  const { t } = useTranslation();
  const tr = (key: string) => t(`settings.sources.testRetrieval.${key}`);

  if (chunk.score === null || chunk.score_kind === null) {
    return (
      <span className="text-muted-foreground text-xs" title={tr('noScoreHint')}>
        {tr('noScore')}
      </span>
    );
  }

  const label =
    chunk.score_kind === 'cosine_similarity'
      ? tr('scoreKinds.cosine_similarity')
      : chunk.score_kind === 'l2_distance'
        ? tr('scoreKinds.l2_distance')
        : tr('scoreKinds.rrf');

  return (
    <span className="text-muted-foreground font-mono text-xs">
      <span className="mr-1 font-sans">{label}</span>
      {chunk.score.toFixed(3)}
    </span>
  );
}

export default function TestRetrievalModal({
  modalState,
  setModalState,
  document,
  hybridAvailable = false,
  graphRAGAvailable = false,
  availableModels = [],
}: TestRetrievalModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const tr = (key: string, opts?: Record<string, unknown>) =>
    t(`settings.sources.testRetrieval.${key}`, opts ?? {});

  const [query, setQuery] = useState('');
  const [options, setOptions] = useState<RetrievalOptionsValue>(() =>
    configToOptions(document?.config),
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RetrievalResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      setOptions(configToOptions(document?.config));
      setQuery('');
      setResult(null);
      setError(null);
      setRunning(false);
      setExpanded(new Set());
    }
  }, [modalState, document]);

  const closeModal = () => setModalState('INACTIVE');

  const prescreenValid = isPrescreenConfigValid(options);
  const canRun = !!document?.id && !!query.trim() && !running && prescreenValid;

  const handleRun = async () => {
    if (!canRun || !document?.id) return;
    setRunning(true);
    setError(null);
    try {
      const response = await userService.testSourceRetrieval(
        document.id,
        {
          query: query.trim(),
          // Send the form's retrieval block as an ad-hoc override — the backend
          // never persists it, so the source's saved config is untouched.
          retrieval: optionsToConfig(options).retrieval,
        },
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        setError(data?.message || tr('errors.failed'));
        setResult(null);
        return;
      }
      setResult(data as RetrievalResult);
      setExpanded(new Set());
    } catch {
      setError(tr('errors.failed'));
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  const toggleExpanded = (rank: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(rank)) next.delete(rank);
      else next.add(rank);
      return next;
    });
  };

  // A threshold that filtered everything out is the single most likely reason
  // for an empty result, so say so instead of a bare "no chunks". Read the
  // threshold off the completed run, not the live form — editing the field
  // after a run must not rewrite that run's explanation.
  const ranThreshold = result?.retrieval?.score_threshold ?? null;
  const emptyMessage = ranThreshold
    ? tr('emptyWithThreshold', { threshold: ranThreshold })
    : tr('empty');

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && closeModal()}
      title={tr('title')}
      description={
        document?.name
          ? tr('subtitle', { name: document.name })
          : tr('subtitleGeneric')
      }
      // xl, like PromptsModal, so the two large modals read as one family.
      size="xl"
      mobileVariant="sheet"
    >
      <div className="flex flex-col">
        <div className="flex flex-col gap-4">
          <div className="flex flex-row items-center gap-2">
            <Input
              type="text"
              value={query}
              autoFocus
              placeholder={tr('queryPlaceholder')}
              shape="pill"
              className="flex-1"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRun();
              }}
            />
            <Button
              type="button"
              disabled={!canRun}
              onClick={handleRun}
              size="field"
              shape="pill"
              loading={running}
              className="shrink-0"
            >
              {tr('run')}
            </Button>
          </div>

          <RetrievalOptions
            value={options}
            onChange={setOptions}
            queryOnly
            hybridAvailable={hybridAvailable}
            graphRAGAvailable={graphRAGAvailable}
            availableModels={availableModels}
          />

          <p className="text-muted-foreground text-xs">{tr('notSavedHint')}</p>

          {!prescreenValid && (
            <Alert variant="warning">
              <TriangleAlert className="size-4" aria-hidden="true" />
              <AlertDescription>
                {t('settings.sources.configModal.prescreenInvalidHint')}
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive">
              <CircleAlert className="size-4" aria-hidden="true" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {result && (
            <div className="flex flex-col gap-3">
              <div className="text-muted-foreground flex flex-row items-center justify-between text-xs">
                <span>
                  {tr('resultSummary', {
                    count: result.total,
                    retriever: result.retriever,
                  })}
                </span>
                <span>{tr('latency', { ms: result.latency_ms })}</span>
              </div>

              {result.chunks.length === 0 ? (
                <div className="border-border text-muted-foreground rounded-xl border border-dashed p-6 text-center text-sm">
                  {emptyMessage}
                </div>
              ) : (
                result.chunks.map((chunk) => {
                  const isOpen = expanded.has(chunk.rank);
                  return (
                    <div
                      key={chunk.rank}
                      className="border-border bg-muted rounded-xl border p-4"
                    >
                      <div className="mb-2 flex flex-row items-center justify-between gap-2">
                        <div className="flex min-w-0 flex-row items-center gap-2">
                          <span className="bg-muted text-muted-foreground shrink-0 rounded-md px-2 py-0.5 font-mono text-xs">
                            #{chunk.rank}
                          </span>
                          <span
                            className="text-foreground truncate text-sm font-medium"
                            title={chunk.source ?? undefined}
                          >
                            {chunk.filename || chunk.title || chunk.source}
                          </span>
                        </div>
                        <div className="flex shrink-0 flex-row items-center gap-3">
                          <ScoreBadge chunk={chunk} />
                          <span className="text-muted-foreground text-xs">
                            {chunk.tokens} {t('settings.sources.tokensUnit')}
                          </span>
                        </div>
                      </div>
                      {/* Chunks routinely start and end with blank lines; left
                          in, the collapsed clamp spends its 3 lines on nothing
                          and the preview looks empty. */}
                      <p
                        className={cn(
                          'text-muted-foreground text-sm whitespace-pre-wrap',
                          !isOpen && 'line-clamp-3',
                        )}
                      >
                        {chunk.text.trim()}
                      </p>
                      <Button
                        type="button"
                        variant="link"
                        size="xs"
                        onClick={() => toggleExpanded(chunk.rank)}
                        className="-ml-2"
                      >
                        {isOpen ? tr('showLess') : tr('showMore')}
                      </Button>
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
