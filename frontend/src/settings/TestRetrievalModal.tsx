import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { EmptyState } from '../components/ui/empty-state';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { cn } from '../lib/utils';
import { ActiveState, Doc } from '../models/misc';
import type { Model } from '../models/types';
import { selectToken } from '../preferences/preferenceSlice';
import { EMPTY_VALUE } from '../utils/dateTimeUtils';

import RetrievalOptions, {
  configToOptions,
  type DecisionFeatures,
  NO_DECISION_FEATURES,
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
  // The decision model's p(relevant), when a relevance stage ordered the
  // result by it.
  relevance?: number | null;
};

/** A chunk the stages received, as `compare` lists them in retriever order. */
export type RetrievalCandidate = Omit<RetrievedChunk, 'rank'> & {
  // Its place in the result, or null when it was not kept.
  rank: number | null;
  rank_before: number;
  kept: boolean;
  // In the selection the retrieval makes without the model.
  baseline: boolean;
};

/** What the decision model did in the run; null when it did not run. */
export type RelevanceRun = {
  applied: boolean;
  fallback: string | null;
  latency_ms: number;
};

type RetrievalResult = {
  query: string;
  retriever: string;
  // The config the run actually used, echoed back by the backend.
  retrieval: { score_threshold: number | null };
  total: number;
  latency_ms: number;
  chunks: RetrievedChunk[];
  relevance?: RelevanceRun | null;
  candidates?: RetrievalCandidate[];
};

interface TestRetrievalModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  document: Doc | null;
  hybridAvailable?: boolean;
  graphRAGAvailable?: boolean;
  availableModels?: Model[];
  // The decision-model controls the operator turned on (/api/config).
  decision?: DecisionFeatures;
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

/** A chunk's relevance from the decision model, as a percentage. */
export function RelevanceScore({ relevance }: { relevance?: number | null }) {
  const { t } = useTranslation();
  if (typeof relevance !== 'number') return null;
  return (
    <span className="text-muted-foreground font-mono text-xs">
      <span className="mr-1 font-sans">
        {t('settings.sources.testRetrieval.relevance')}
      </span>
      {formatPercent(relevance)}
    </span>
  );
}

function formatPercent(relevance: number): string {
  return `${Math.round(relevance * 100)}%`;
}

/** One line on what the decision model did in a run. */
export function relevanceRunText(
  run: RelevanceRun,
  tr: (key: string, opts?: Record<string, unknown>) => string,
): string {
  if (run.fallback)
    return tr('relevanceRun.fallback', { reason: run.fallback });
  if (!run.applied) return tr('relevanceRun.monitor');
  return tr('relevanceRun.applied', { ms: run.latency_ms });
}

/**
 * The candidates the stages received, in retriever order, beside what became
 * of each: kept (and where), promoted from past the retriever's own
 * selection, or dropped from it.
 */
export function CandidateComparison({
  candidates,
}: {
  candidates: RetrievalCandidate[];
}) {
  const { t } = useTranslation();
  const tr = (key: string, opts?: Record<string, unknown>) =>
    t(`settings.sources.testRetrieval.${key}`, opts ?? {});

  const outcome = (c: RetrievalCandidate) => {
    if (c.kept && !c.baseline)
      return (
        <Badge variant="success">
          {tr('compareStatus.promoted', { rank: c.rank })}
        </Badge>
      );
    if (c.kept)
      return (
        <Badge variant="neutral">
          {tr('compareStatus.kept', { rank: c.rank })}
        </Badge>
      );
    if (c.baseline)
      return <Badge variant="warning">{tr('compareStatus.dropped')}</Badge>;
    return (
      <span className="text-muted-foreground">
        {tr('compareStatus.notKept')}
      </span>
    );
  };

  return (
    <div className="flex flex-col gap-2">
      <SectionHeader
        as="h4"
        size="xs"
        title={tr('compareTitle')}
        description={tr('compareDescription')}
      />
      <TableContainer>
        <Table minWidth="min-w-0">
          <TableHead>
            <TableRow>
              <TableHeader width="5rem" align="right">
                {tr('compareColumns.before')}
              </TableHeader>
              <TableHeader>{tr('compareColumns.chunk')}</TableHeader>
              <TableHeader width="6rem" align="right">
                {tr('compareColumns.relevance')}
              </TableHeader>
              <TableHeader width="9rem">
                {tr('compareColumns.outcome')}
              </TableHeader>
            </TableRow>
          </TableHead>
          <TableBody>
            {candidates.map((c) => (
              <TableRow key={c.rank_before}>
                <TableCell align="right" className="tabular-nums">
                  {c.rank_before}
                </TableCell>
                <TableCell className="text-sm">
                  <span
                    className="line-clamp-2 wrap-anywhere"
                    title={c.filename || c.title || c.source || undefined}
                  >
                    {c.text.trim()}
                  </span>
                </TableCell>
                <TableCell align="right" className="tabular-nums">
                  {typeof c.relevance === 'number'
                    ? formatPercent(c.relevance)
                    : EMPTY_VALUE}
                </TableCell>
                <TableCell>{outcome(c)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  );
}

export default function TestRetrievalModal({
  modalState,
  setModalState,
  document,
  hybridAvailable = false,
  graphRAGAvailable = false,
  availableModels = [],
  decision = NO_DECISION_FEATURES,
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
  const [compare, setCompare] = useState(false);
  // Comparing with retriever order shows what the decision model changed, so
  // it is offered only where the operator turned the model on.
  const canCompare = decision.rerank || decision.prescreen;

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      setOptions(configToOptions(document?.config));
      setQuery('');
      setResult(null);
      setError(null);
      setRunning(false);
      setExpanded(new Set());
      setCompare(false);
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
          ...(canCompare && compare ? { compare: true } : {}),
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
          ? tr('subtitle', {
              name: document.name,
              // React escapes the text; i18next escaping it too shows "&amp;".
              interpolation: { escapeValue: false },
            })
          : tr('subtitleGeneric')
      }
      // xl, like PromptsModal, so the two large modals read as one family.
      size="xl"
    >
      <div className="flex flex-col">
        <div className="flex flex-col gap-4">
          <div className="flex flex-row items-center gap-2">
            <Input
              type="text"
              value={query}
              placeholder={tr('queryPlaceholder')}
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
            decision={decision}
          />

          {canCompare && (
            <SettingRows>
              <SettingRow
                label={tr('compare')}
                htmlFor="test-retrieval-compare"
                description={tr('compareHint')}
                alignStart
              >
                <Switch
                  id="test-retrieval-compare"
                  checked={compare}
                  onCheckedChange={setCompare}
                />
              </SettingRow>
            </SettingRows>
          )}

          <p className="text-muted-foreground text-xs">{tr('notSavedHint')}</p>

          {!prescreenValid && (
            <Alert variant="warning">
              <AlertDescription>
                {t('settings.sources.configModal.prescreenInvalidHint')}
              </AlertDescription>
            </Alert>
          )}

          {error && (
            <Alert variant="destructive">
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
                  {result.relevance
                    ? ` · ${relevanceRunText(result.relevance, tr)}`
                    : null}
                </span>
                <span>{tr('latency', { ms: result.latency_ms })}</span>
              </div>

              {result.chunks.length === 0 ? (
                <EmptyState
                  size="sm"
                  illustration="none"
                  title={emptyMessage}
                />
              ) : (
                result.chunks.map((chunk) => {
                  const isOpen = expanded.has(chunk.rank);
                  return (
                    <Card key={chunk.rank} variant="outline" className="gap-2">
                      <div className="flex flex-row items-center justify-between gap-2">
                        <div className="flex min-w-0 flex-row items-center gap-2">
                          <Badge variant="neutral" className="font-mono">
                            #{chunk.rank}
                          </Badge>
                          <span
                            className="text-foreground truncate text-sm font-medium"
                            title={chunk.source ?? undefined}
                          >
                            {chunk.filename || chunk.title || chunk.source}
                          </span>
                        </div>
                        <div className="flex shrink-0 flex-row items-center gap-3">
                          <ScoreBadge chunk={chunk} />
                          <RelevanceScore relevance={chunk.relevance} />
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
                        className="-ml-2 self-start"
                      >
                        {isOpen ? tr('showLess') : tr('showMore')}
                      </Button>
                    </Card>
                  );
                })
              )}

              {result.candidates && result.candidates.length > 0 && (
                <CandidateComparison candidates={result.candidates} />
              )}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
