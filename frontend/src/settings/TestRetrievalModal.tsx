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
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
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
import { ActiveState, Doc, type SourceRetrievalConfig } from '../models/misc';
import type { Model } from '../models/types';
import { selectToken } from '../preferences/preferenceSlice';
import { can } from '../utils/accessUtils';
import { EMPTY_VALUE } from '../utils/dateTimeUtils';

import RetrievalOptions, {
  configToOptions,
  type DecisionFeatures,
  NO_DECISION_FEATURES,
  RELEVANCE_PRESETS,
  type RelevanceStrictness,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
  strictnessOf,
  withStrictness,
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
  // After "Save to source" stored the tested retrieval block on the source.
  onSaved?: (retrieval: SourceRetrievalConfig) => void;
}

const STRICTNESS: RelevanceStrictness[] = [
  'off',
  'reorder',
  ...(Object.keys(RELEVANCE_PRESETS) as RelevanceStrictness[]),
];

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
  if (run.fallback || !run.applied)
    return tr('relevanceRun.fallback', { reason: run.fallback ?? 'skipped' });
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
  onSaved,
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
  // The retrieval block the shown result ran with: what "Save to source" saves.
  const [tested, setTested] = useState<SourceRetrievalConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Comparing with retriever order and picking a strictness show what the
  // relevance model changes, so they are offered only where it is on.
  const relevanceAvailable = decision.relevance;
  const canSave = !!document && can(document, 'edit');

  useEffect(() => {
    if (modalState === 'ACTIVE') {
      setOptions(configToOptions(document?.config));
      setQuery('');
      setResult(null);
      setError(null);
      setRunning(false);
      setExpanded(new Set());
      setCompare(false);
      setTested(null);
      setSaving(false);
      setSaved(false);
      setSaveError(null);
    }
  }, [modalState, document]);

  const closeModal = () => setModalState('INACTIVE');

  const prescreenValid = isPrescreenConfigValid(options);
  const canRun = !!document?.id && !!query.trim() && !running && prescreenValid;
  const retrieval = optionsToConfig(options).retrieval;
  // Saves only what the shown result ran with, so a form edited since does
  // not land on the source untested.
  const testedShown =
    !!result &&
    tested !== null &&
    JSON.stringify(tested) === JSON.stringify(retrieval);

  const handleRun = async (next: RetrievalOptionsValue = options) => {
    if (!document?.id || !query.trim() || running) return;
    if (!isPrescreenConfigValid(next)) return;
    const ran = optionsToConfig(next).retrieval ?? null;
    setRunning(true);
    setError(null);
    setSaved(false);
    setSaveError(null);
    try {
      const response = await userService.testSourceRetrieval(
        document.id,
        {
          query: query.trim(),
          // Send the form's retrieval block as an ad-hoc override — the backend
          // never persists it, so the source's saved config is untouched.
          retrieval: ran,
          ...(relevanceAvailable && compare ? { compare: true } : {}),
        },
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        setError(data?.message || tr('errors.failed'));
        setResult(null);
        setTested(null);
        return;
      }
      setResult(data as RetrievalResult);
      setTested(ran);
      setExpanded(new Set());
    } catch {
      setError(tr('errors.failed'));
      setResult(null);
      setTested(null);
    } finally {
      setRunning(false);
    }
  };

  // A strictness pick re-runs the test with it, once there is a query.
  const pickStrictness = (strictness: RelevanceStrictness) => {
    const next = withStrictness(options, strictness);
    setOptions(next);
    handleRun(next);
  };

  // The PATCH keeps the sections it is not sent, so the tested retrieval
  // block goes alone and chunking and graph stay as saved.
  const handleSave = async () => {
    if (!document?.id || !testedShown || !canSave) return;
    setSaving(true);
    setSaved(false);
    setSaveError(null);
    try {
      const response = await userService.updateSourceConfig(
        document.id,
        { retrieval: tested },
        token,
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.success) {
        setSaveError(
          response.status === 403
            ? t('settings.sources.configModal.errors.forbidden')
            : data?.message ||
                t('settings.sources.configModal.errors.saveFailed'),
        );
        return;
      }
      setSaved(true);
      onSaved?.(tested);
    } catch {
      setSaveError(t('settings.sources.configModal.errors.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const strictness = strictnessOf(options);

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
              onClick={() => handleRun()}
              size="field"
              loading={running}
              className="shrink-0"
            >
              {tr('run')}
            </Button>
          </div>

          {relevanceAvailable && (
            <ToggleGroup
              type="single"
              value={strictness}
              aria-label={tr('strictness')}
              onValueChange={(v) =>
                v && v !== 'custom' && pickStrictness(v as RelevanceStrictness)
              }
            >
              {STRICTNESS.map((s) => (
                <ToggleGroupItem key={s} value={s}>
                  {s === 'off' || s === 'reorder'
                    ? t(
                        `settings.sources.retrievalOptions.relevance.modes.${s}`,
                      )
                    : t(
                        `settings.sources.retrievalOptions.relevance.presets.${s}`,
                      )}
                </ToggleGroupItem>
              ))}
              {strictness === 'custom' && (
                <ToggleGroupItem value="custom">
                  {t(
                    'settings.sources.retrievalOptions.relevance.presets.custom',
                    {
                      value: options.retrieval.reranker.min_relevance,
                    },
                  )}
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          )}

          <RetrievalOptions
            value={options}
            onChange={setOptions}
            queryOnly
            hybridAvailable={hybridAvailable}
            graphRAGAvailable={graphRAGAvailable}
            availableModels={availableModels}
            decision={decision}
          />

          {relevanceAvailable && (
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

          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <p className="text-muted-foreground text-xs">
              {tr(canSave ? 'notSavedHintEditor' : 'notSavedHint')}
            </p>
            {canSave && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={!testedShown || saved}
                loading={saving}
                onClick={handleSave}
              >
                {tr('saveToSource')}
              </Button>
            )}
          </div>

          {saved && (
            <Alert variant="success">
              <AlertDescription>{tr('savedToSource')}</AlertDescription>
            </Alert>
          )}

          {saveError && (
            <Alert variant="destructive">
              <AlertDescription>{saveError}</AlertDescription>
            </Alert>
          )}

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
