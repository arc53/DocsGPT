import { useId, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

import {
  Collapsible,
  CollapsibleTrigger,
} from '../../components/ui/collapsible';
import { Input } from '../../components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { SectionHeader } from '../../components/ui/section-header';
import { SettingRow, SettingRows } from '../../components/ui/setting-row';
import { Switch } from '../../components/ui/switch';
import { ToggleGroup, ToggleGroupItem } from '../../components/ui/toggle-group';
import type {
  ChunkingStrategy,
  GraphSeedStrategy,
  RetrievalExposure,
  SourceConfig,
} from '../../models/misc';
import type { Model } from '../../models/types';

// Defaults mirror the backend SourceConfig
// (docsgpt/storage/db/source_config.py). A form seeded with these and sent
// verbatim reproduces today's behavior, so the backend's "absent == default"
// contract is preserved either way.
export const DEFAULT_PRESCREEN = {
  candidate_k: 40,
  model: null as string | null,
  batch_size: 10,
  max_keep: 8,
};

// The relevance model scores at most this many candidates in its one call
// (backend DECISION_MAX_CANDIDATES), and this many when a source sets none
// (backend DEFAULT_CANDIDATE_K).
export const DECISION_MAX_CANDIDATES = 100;
export const DEFAULT_CANDIDATE_K = 20;

/**
 * A source's relevance: off, the chunks reordered by the relevance model, or
 * reordered and those below `min_relevance` dropped. Stored as `reranker`:
 * null when off, `min_relevance` null when it only reorders.
 */
export type RelevanceMode = 'off' | 'reorder' | 'filter';

/** The filter strictness presets, as the minimum relevance a kept chunk needs. */
export const RELEVANCE_PRESETS = {
  loose: 0.1,
  balanced: 0.3,
  strict: 0.5,
} as const;

export type RelevancePreset = keyof typeof RELEVANCE_PRESETS;

const PRESET_KEYS = Object.keys(RELEVANCE_PRESETS) as RelevancePreset[];

// What a newly chosen filter starts at.
const DEFAULT_MIN_RELEVANCE = RELEVANCE_PRESETS.balanced;

/** The preset a minimum relevance matches, or null for a custom value. */
export function relevancePreset(minRelevance: number): RelevancePreset | null {
  return (
    PRESET_KEYS.find(
      (key) => Math.abs(RELEVANCE_PRESETS[key] - minRelevance) < 1e-9,
    ) ?? null
  );
}

/** One pick of the Off / Reorder / Loose / Balanced / Strict scale. */
export type RelevanceStrictness = 'off' | 'reorder' | RelevancePreset;

/** Where a form's relevance sits on that scale; `custom` for an exact value. */
export function strictnessOf(
  value: RetrievalOptionsValue,
): RelevanceStrictness | 'custom' {
  const { mode, min_relevance } = value.retrieval.reranker;
  if (mode !== 'filter') return mode;
  return relevancePreset(min_relevance) ?? 'custom';
}

/**
 * The form with its relevance set to `strictness`. Relevance and LLM
 * screening are alternatives, so any relevance turns the screening off.
 */
export function withStrictness(
  value: RetrievalOptionsValue,
  strictness: RelevanceStrictness,
): RetrievalOptionsValue {
  const reranker = value.retrieval.reranker;
  const next =
    strictness === 'off' || strictness === 'reorder'
      ? { ...reranker, mode: strictness }
      : {
          ...reranker,
          mode: 'filter' as const,
          min_relevance: RELEVANCE_PRESETS[strictness],
        };
  return withRelevance(value, next);
}

function withRelevance(
  value: RetrievalOptionsValue,
  reranker: RetrievalOptionsValue['retrieval']['reranker'],
): RetrievalOptionsValue {
  return {
    ...value,
    retrieval: {
      ...value.retrieval,
      reranker,
      prescreen:
        reranker.mode === 'off'
          ? value.retrieval.prescreen
          : { ...value.retrieval.prescreen, enabled: false },
    },
  };
}

/**
 * The decision-model controls the operator turned on, from /api/config.
 * While `relevance` is false the Relevance section is hidden, and a source's
 * stored value is kept as it is.
 */
export type DecisionFeatures = { relevance: boolean };

export const NO_DECISION_FEATURES: DecisionFeatures = { relevance: false };

/** Read `DecisionFeatures` off an /api/config response; all off without the model. */
export function decisionFeatures(config: unknown): DecisionFeatures {
  const c = (config ?? {}) as Record<string, unknown>;
  return {
    relevance:
      c.decision_available === true && c.decision_relevance_enabled === true,
  };
}

export const MAX_CHUNK_TOKENS = 4096;

function clampChunkTokens(value: number): number {
  return Math.min(MAX_CHUNK_TOKENS, Math.max(1, value || 1));
}

// Fully-populated form shape so every control is controlled. Prescreen is
// flattened into the form (with an `enabled` flag) and re-nested on serialize.
// `kind` is carried so serialization preserves a source's behavior selector
// (classic/wiki/graphrag) instead of silently downgrading it.
export type RetrievalOptionsValue = {
  kind: string;
  chunking: {
    strategy: ChunkingStrategy;
    max_tokens: number;
    min_tokens: number;
    duplicate_headers: boolean;
  };
  retrieval: {
    retriever: string;
    exposure: RetrievalExposure;
    chunks: number;
    score_threshold: number | null;
    rephrase_query: boolean;
    show_links: boolean;
    prescreen: {
      enabled: boolean;
      candidate_k: number;
      model: string | null;
      batch_size: number;
      max_keep: number;
    };
    reranker: {
      mode: RelevanceMode;
      // The filter's threshold; kept while the mode is not `filter` so
      // switching back restores it.
      min_relevance: number;
      // null: DEFAULT_CANDIDATE_K.
      candidate_k: number | null;
    };
    graph: {
      seed_strategy: GraphSeedStrategy;
      passage_nodes: boolean;
      blend_vector: boolean;
    };
  };
  graph: {
    extraction_model: string | null;
    max_chunks: number | null;
    gleanings: number;
  };
};

export const DEFAULT_RETRIEVAL_OPTIONS: RetrievalOptionsValue = {
  kind: 'classic',
  chunking: {
    strategy: 'classic_chunk',
    max_tokens: 1250,
    min_tokens: 150,
    duplicate_headers: false,
  },
  retrieval: {
    retriever: 'classic',
    exposure: 'prefetch',
    chunks: 6,
    score_threshold: null,
    rephrase_query: true,
    show_links: true,
    prescreen: {
      enabled: false,
      ...DEFAULT_PRESCREEN,
    },
    reranker: {
      mode: 'off',
      min_relevance: DEFAULT_MIN_RELEVANCE,
      candidate_k: null,
    },
    // The configuration that measured best across the corpora tested.
    graph: {
      seed_strategy: 'entities',
      passage_nodes: true,
      blend_vector: true,
    },
  },
  graph: {
    extraction_model: null,
    max_chunks: null,
    gleanings: 0,
  },
};

const CHUNKING_STRATEGIES: ChunkingStrategy[] = [
  'classic_chunk',
  'recursive',
  'markdown',
  'parent_child',
  'semantic',
];

const CLASSIC_RETRIEVER = 'classic';
const HYBRID_RETRIEVER = 'hybrid';
const GRAPHRAG_RETRIEVER = 'graphrag';
// Sentinel select value for "use the instance default model" (Select can't take
// an empty/null item value); maps to extraction_model = null on change.
const GRAPH_DEFAULT_MODEL = '__default__';

/**
 * The similarity threshold (`score_threshold`) is a cosine-similarity cutoff
 * on the retriever's own scores; the hybrid (RRF) and graphrag
 * (PPR) retrievers don't produce comparable scores, so the control is hidden
 * for them.
 */
export function scoreThresholdHidden(retriever: string): boolean {
  return retriever === HYBRID_RETRIEVER || retriever === GRAPHRAG_RETRIEVER;
}

/**
 * Retriever options to offer. Classic is always available; hybrid and graphrag
 * are gated on instance support, but the currently-selected retriever is always
 * included so an existing source never renders an out-of-range select.
 */
export function availableRetrievers(
  current: string,
  hybridAvailable: boolean,
  graphRAGAvailable: boolean,
): string[] {
  const options = [CLASSIC_RETRIEVER];
  if (hybridAvailable || current === HYBRID_RETRIEVER) {
    options.push(HYBRID_RETRIEVER);
  }
  if (graphRAGAvailable || current === GRAPHRAG_RETRIEVER) {
    options.push(GRAPHRAG_RETRIEVER);
  }
  return options;
}

// Synced services whose files have a web link the ingest stores.
const LINKED_FILE_PROVIDERS = new Set([
  'google_drive',
  'share_point',
  'confluence',
]);

/** True when a source synced from `provider` stores each file's web link. */
export function sourceHasFileLinks(provider?: string | null): boolean {
  return !!provider && LINKED_FILE_PROVIDERS.has(provider);
}

/**
 * Group eyebrow: an uppercase, tracked title with a normal-weight ` · tag`
 * suffix, set above the field rows of a group.
 */
function GroupHeader({ title, tag }: { title: string; tag: string }) {
  return (
    <SectionHeader
      as="h4"
      size="sm"
      title={
        <>
          {title}
          <span className="text-muted-foreground font-normal normal-case">
            {' · '}
            {tag}
          </span>
        </>
      }
    />
  );
}

/**
 * Hydrate the form value from a stored (possibly partial/absent) SourceConfig,
 * filling every missing field with the documented default. Lenient on read so a
 * legacy `{}` row produces an all-defaults form.
 */
export function configToOptions(config?: SourceConfig): RetrievalOptionsValue {
  const chunking = config?.chunking ?? {};
  const retrieval = config?.retrieval ?? {};
  const prescreen = retrieval.prescreen ?? null;
  const reranker = retrieval.reranker ?? null;
  const retrievalGraph = retrieval.graph ?? {};
  const graph = config?.graph ?? {};
  const d = DEFAULT_RETRIEVAL_OPTIONS;
  return {
    kind: config?.kind ?? d.kind,
    chunking: {
      strategy: chunking.strategy ?? d.chunking.strategy,
      max_tokens: clampChunkTokens(
        chunking.max_tokens ?? d.chunking.max_tokens,
      ),
      min_tokens: chunking.min_tokens ?? d.chunking.min_tokens,
      duplicate_headers:
        chunking.duplicate_headers ?? d.chunking.duplicate_headers,
    },
    retrieval: {
      retriever: retrieval.retriever ?? d.retrieval.retriever,
      exposure: retrieval.exposure ?? d.retrieval.exposure,
      chunks: retrieval.chunks ?? d.retrieval.chunks,
      score_threshold: retrieval.score_threshold ?? d.retrieval.score_threshold,
      rephrase_query: retrieval.rephrase_query ?? d.retrieval.rephrase_query,
      show_links: retrieval.show_links ?? d.retrieval.show_links,
      prescreen: {
        enabled: prescreen != null,
        candidate_k: prescreen?.candidate_k ?? DEFAULT_PRESCREEN.candidate_k,
        model: prescreen?.model ?? DEFAULT_PRESCREEN.model,
        batch_size: prescreen?.batch_size ?? DEFAULT_PRESCREEN.batch_size,
        max_keep: prescreen?.max_keep ?? DEFAULT_PRESCREEN.max_keep,
      },
      reranker: {
        mode:
          reranker === null
            ? 'off'
            : (reranker.min_relevance ?? 0) > 0
              ? 'filter'
              : 'reorder',
        min_relevance:
          reranker?.min_relevance && reranker.min_relevance > 0
            ? reranker.min_relevance
            : DEFAULT_MIN_RELEVANCE,
        candidate_k: reranker?.candidate_k ?? null,
      },
      graph: {
        seed_strategy:
          retrievalGraph.seed_strategy ?? d.retrieval.graph.seed_strategy,
        passage_nodes:
          retrievalGraph.passage_nodes ?? d.retrieval.graph.passage_nodes,
        blend_vector:
          retrievalGraph.blend_vector ?? d.retrieval.graph.blend_vector,
      },
    },
    graph: {
      extraction_model: graph.extraction_model ?? d.graph.extraction_model,
      max_chunks: graph.max_chunks ?? d.graph.max_chunks,
      gleanings: graph.gleanings ?? d.graph.gleanings,
    },
  };
}

/**
 * Serialize the form value into a full SourceConfig object the backend accepts.
 * The backend uses `extra="forbid"` and re-validates the whole object, so we
 * always send the complete (kind + chunking + retrieval + graph) shape.
 * Prescreen is re-nested to `null` when disabled. `kind` is preserved from the
 * value and forced to `graphrag` when the graphrag retriever is chosen (so the
 * create-flow ingest auto-extracts), never silently downgrading wiki/graphrag.
 */
export function optionsToConfig(value: RetrievalOptionsValue): SourceConfig {
  const ps = value.retrieval.prescreen;
  const rr = value.retrieval.reranker;
  const kind =
    value.retrieval.retriever === GRAPHRAG_RETRIEVER ? 'graphrag' : value.kind;
  return {
    kind,
    chunking: {
      strategy: value.chunking.strategy,
      max_tokens: clampChunkTokens(value.chunking.max_tokens),
      min_tokens: value.chunking.min_tokens,
      duplicate_headers: value.chunking.duplicate_headers,
    },
    retrieval: {
      retriever: value.retrieval.retriever,
      exposure: value.retrieval.exposure,
      chunks: value.retrieval.chunks,
      score_threshold: value.retrieval.score_threshold,
      rephrase_query: value.retrieval.rephrase_query,
      show_links: value.retrieval.show_links,
      prescreen: ps.enabled
        ? {
            candidate_k: ps.candidate_k,
            model: ps.model?.trim() ? ps.model.trim() : null,
            batch_size: ps.batch_size,
            max_keep: ps.max_keep,
          }
        : null,
      reranker:
        rr.mode === 'off'
          ? null
          : {
              type: 'decision',
              min_relevance: rr.mode === 'filter' ? rr.min_relevance : null,
              candidate_k: rr.candidate_k,
            },
      graph: {
        seed_strategy: value.retrieval.graph.seed_strategy,
        passage_nodes: value.retrieval.graph.passage_nodes,
        blend_vector: value.retrieval.graph.blend_vector,
      },
    },
    graph: {
      extraction_model: value.graph.extraction_model?.trim()
        ? value.graph.extraction_model.trim()
        : null,
      max_chunks: value.graph.max_chunks,
      gleanings: value.graph.gleanings,
    },
  };
}

/**
 * True when the prescreen config is consistent with the backend's rules.
 * Disabled prescreen is always valid; enabled requires `candidate_k >= chunks`
 * and `max_keep <= candidate_k` (mirrors SourceConfig/PreScreenConfig).
 */
export function isPrescreenConfigValid(value: RetrievalOptionsValue): boolean {
  const ps = value.retrieval.prescreen;
  if (!ps.enabled) return true;
  return (
    ps.candidate_k >= value.retrieval.chunks && ps.max_keep <= ps.candidate_k
  );
}

/** True when the form differs from the stored config's chunking group only. */
export function chunkingChanged(
  before: RetrievalOptionsValue,
  after: RetrievalOptionsValue,
): boolean {
  return (
    before.chunking.strategy !== after.chunking.strategy ||
    before.chunking.max_tokens !== after.chunking.max_tokens ||
    before.chunking.min_tokens !== after.chunking.min_tokens ||
    before.chunking.duplicate_headers !== after.chunking.duplicate_headers
  );
}

type RetrievalOptionsProps = {
  value: RetrievalOptionsValue;
  onChange: (value: RetrievalOptionsValue) => void;
  // When true the section is always expanded (modal use); when false it renders
  // its own collapsible toggle (create-flow use). Defaults to collapsible.
  alwaysOpen?: boolean;
  disabled?: boolean;
  // Adds the hybrid retriever option when the instance supports it (pgvector,
  // from /api/config).
  hybridAvailable?: boolean;
  // Adds the graphrag retriever option + extraction config when the instance
  // supports it (pgvector + GRAPHRAG_ENABLED, from /api/config).
  graphRAGAvailable?: boolean;
  // Models for the graph extraction-model picker, same shape as the agent form.
  availableModels?: Model[];
  // Shows only the knobs that change what a query retrieves, hiding the
  // ingest-time groups (chunking, graph extraction) and `exposure` (which picks
  // *when* a source is searched at answer time, not what comes back). Used by
  // the retrieval tester, where those knobs cannot affect the result and
  // showing them would imply they do.
  queryOnly?: boolean;
  // Shows the retrieval groups only, hiding the ingest-time ones: the admin's
  // defaults for new sources hold a retrieval config and nothing else.
  retrievalOnly?: boolean;
  // The collapsible toggle's label, where "Advanced settings" alone would be
  // unclear (the connect wizard). Defaults to the shared title.
  title?: string;
  // The decision-model controls the operator turned on (/api/config); the
  // Relevance section is hidden while the model is off.
  decision?: DecisionFeatures;
  // Shows the file-link switch: the source is synced from a service whose
  // files have web links (see `sourceHasFileLinks`).
  linksAvailable?: boolean;
};

/**
 * Shared "Retrieval options" panel reused by the create flow (Upload) and the
 * edit modal (SourceConfigModal). Groups live "Retrieval" knobs from
 * re-ingest-gated "Chunking" knobs, with a visible note on the chunking group.
 */
export default function RetrievalOptions({
  value,
  onChange,
  alwaysOpen = false,
  disabled = false,
  hybridAvailable = false,
  graphRAGAvailable = false,
  availableModels = [],
  queryOnly = false,
  retrievalOnly = false,
  title,
  decision = NO_DECISION_FEATURES,
  linksAvailable = false,
}: RetrievalOptionsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const expanded = alwaysOpen || open;
  const bodyId = useId();
  const advancedId = useId();
  // Follows the values (open while one is set) until the user toggles it.
  const [advancedToggled, setAdvancedToggled] = useState<boolean | null>(null);
  const ingestHidden = queryOnly || retrievalOnly;

  const strategyOptions = useMemo(
    () =>
      CHUNKING_STRATEGIES.map((s) => ({
        value: s,
        label: t(`settings.sources.retrievalOptions.chunking.strategies.${s}`),
      })),
    [t],
  );

  const isGraphRAG = value.retrieval.retriever === GRAPHRAG_RETRIEVER;
  const retrievers = useMemo(
    () =>
      availableRetrievers(
        value.retrieval.retriever,
        hybridAvailable,
        graphRAGAvailable,
      ),
    [value.retrieval.retriever, hybridAvailable, graphRAGAvailable],
  );

  const setRetrieval = (patch: Partial<RetrievalOptionsValue['retrieval']>) => {
    onChange({
      ...value,
      retrieval: { ...value.retrieval, ...patch },
    });
  };

  const setChunking = (patch: Partial<RetrievalOptionsValue['chunking']>) => {
    onChange({
      ...value,
      chunking: { ...value.chunking, ...patch },
    });
  };

  const setPrescreen = (
    patch: Partial<RetrievalOptionsValue['retrieval']['prescreen']>,
  ) => {
    setRetrieval({
      prescreen: { ...value.retrieval.prescreen, ...patch },
    });
  };

  const setReranker = (
    patch: Partial<RetrievalOptionsValue['retrieval']['reranker']>,
  ) => {
    onChange(withRelevance(value, { ...value.retrieval.reranker, ...patch }));
  };

  // LLM screening is the alternative to relevance: turning it on turns
  // relevance off.
  const enablePrescreen = (checked: boolean) => {
    setRetrieval({
      prescreen: { ...value.retrieval.prescreen, enabled: checked },
      ...(checked
        ? { reranker: { ...value.retrieval.reranker, mode: 'off' as const } }
        : {}),
    });
  };

  const setGraph = (patch: Partial<RetrievalOptionsValue['graph']>) => {
    onChange({
      ...value,
      graph: { ...value.graph, ...patch },
    });
  };

  const setGraphRetrieval = (
    patch: Partial<RetrievalOptionsValue['retrieval']['graph']>,
  ) => {
    setRetrieval({ graph: { ...value.retrieval.graph, ...patch } });
  };

  const modelOptions = useMemo(() => {
    const builtin: Model[] = [];
    const user: Model[] = [];
    availableModels.forEach((m) =>
      (m.source === 'user' ? user : builtin).push(m),
    );
    return { builtin, user };
  }, [availableModels]);

  const tr = (key: string, opts?: Record<string, unknown>) =>
    t(`settings.sources.retrievalOptions.${key}`, opts ?? {});

  const prescreen = value.retrieval.prescreen;
  const reranker = value.retrieval.reranker;
  const relevanceOn = decision.relevance && reranker.mode !== 'off';
  const filtering = decision.relevance && reranker.mode === 'filter';
  const strictness = strictnessOf(value);
  const showSimilarity = !scoreThresholdHidden(value.retrieval.retriever);
  const advancedSet =
    prescreen.enabled ||
    (showSimilarity && value.retrieval.score_threshold !== null) ||
    (relevanceOn && reranker.candidate_k !== null) ||
    (filtering && strictness === 'custom');
  const advancedOpen = advancedToggled ?? advancedSet;

  const relevanceGroup = decision.relevance && (
    <div className="flex flex-col gap-3">
      <GroupHeader title={tr('relevance.title')} tag={tr('relevance.tag')} />
      <SettingRows>
        <SettingRow
          label={tr('relevance.mode')}
          htmlFor="retrieval-relevance-mode"
          description={tr('relevance.modeHint')}
          alignStart
        >
          <Select
            value={reranker.mode}
            disabled={disabled}
            onValueChange={(v) => {
              const mode = v as RelevanceMode;
              setReranker({
                mode,
                ...(mode === 'filter' && !(reranker.min_relevance > 0)
                  ? { min_relevance: DEFAULT_MIN_RELEVANCE }
                  : {}),
              });
            }}
          >
            <SelectTrigger
              id="retrieval-relevance-mode"
              className="w-52"
              size="field"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['off', 'reorder', 'filter'] as const).map((mode) => (
                <SelectItem key={mode} value={mode}>
                  {tr(`relevance.modes.${mode}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </SettingRow>

        {filtering && (
          <SettingRow
            label={tr('relevance.strictness')}
            htmlFor="retrieval-relevance-strictness"
            description={tr('relevance.strictnessHint')}
            alignStart
            stack
          >
            <ToggleGroup
              id="retrieval-relevance-strictness"
              type="single"
              value={strictness}
              disabled={disabled}
              aria-label={tr('relevance.strictness')}
              onValueChange={(v) =>
                v &&
                v !== 'custom' &&
                setReranker({
                  min_relevance: RELEVANCE_PRESETS[v as RelevancePreset],
                })
              }
            >
              {PRESET_KEYS.map((key) => (
                <ToggleGroupItem key={key} value={key}>
                  {tr(`relevance.presets.${key}`)}
                </ToggleGroupItem>
              ))}
              {strictness === 'custom' && (
                <ToggleGroupItem value="custom">
                  {tr('relevance.presets.custom', {
                    value: reranker.min_relevance,
                  })}
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          </SettingRow>
        )}
      </SettingRows>
    </div>
  );

  const advancedRows = (
    <div className="flex flex-col gap-4">
      <SettingRows>
        {filtering && (
          <SettingRow
            label={tr('relevance.minRelevance')}
            htmlFor="retrieval-relevance-min"
            description={tr('relevance.minRelevanceHint')}
            alignStart
          >
            <Input
              id="retrieval-relevance-min"
              type="number"
              min={0}
              max={1}
              step="0.05"
              className="w-24 text-right"
              value={String(reranker.min_relevance)}
              disabled={disabled}
              onChange={(e) =>
                setReranker({
                  min_relevance: Math.min(
                    1,
                    Math.max(0, Number(e.target.value) || 0),
                  ),
                })
              }
            />
          </SettingRow>
        )}

        {relevanceOn && (
          <SettingRow
            label={tr('relevance.candidates')}
            htmlFor="retrieval-relevance-candidates"
            description={tr('relevance.candidatesHint', {
              max: DECISION_MAX_CANDIDATES,
              default: DEFAULT_CANDIDATE_K,
            })}
            alignStart
          >
            <Input
              id="retrieval-relevance-candidates"
              type="number"
              min={1}
              max={DECISION_MAX_CANDIDATES}
              className="w-24 text-right"
              value={String(reranker.candidate_k ?? DEFAULT_CANDIDATE_K)}
              disabled={disabled}
              onChange={(e) =>
                setReranker({
                  candidate_k: Math.min(
                    DECISION_MAX_CANDIDATES,
                    Math.max(1, Number(e.target.value) || 1),
                  ),
                })
              }
            />
          </SettingRow>
        )}

        {showSimilarity && (
          <SettingRow
            label={tr('retrieval.similarityThreshold')}
            htmlFor="retrieval-score-threshold"
            description={tr('retrieval.similarityThresholdHint')}
            alignStart
          >
            <Input
              id="retrieval-score-threshold"
              type="number"
              min={0}
              max={1}
              step="0.01"
              className="w-24 text-right"
              value={
                value.retrieval.score_threshold === null
                  ? ''
                  : String(value.retrieval.score_threshold)
              }
              disabled={disabled}
              placeholder={tr('retrieval.similarityThresholdPlaceholder')}
              onChange={(e) => {
                const raw = e.target.value;
                setRetrieval({
                  score_threshold:
                    raw === ''
                      ? null
                      : Math.min(1, Math.max(0, Number(raw) || 0)),
                });
              }}
            />
          </SettingRow>
        )}

        <SettingRow
          label={tr('prescreen.enable')}
          htmlFor="retrieval-prescreen"
          description={
            decision.relevance ? (
              <>
                {tr('prescreen.warning')} {tr('prescreen.exclusiveHint')}
              </>
            ) : (
              tr('prescreen.warning')
            )
          }
          alignStart
        >
          <Switch
            id="retrieval-prescreen"
            checked={prescreen.enabled}
            disabled={disabled}
            onCheckedChange={enablePrescreen}
          />
        </SettingRow>
      </SettingRows>

      {/* LLM screening's inputs (kept as floating-label cards) */}
      {prescreen.enabled && (
        <div className="border-border ml-4 flex flex-col gap-4 rounded-lg border p-4">
          <Input
            type="number"
            min={value.retrieval.chunks}
            label={tr('prescreen.candidateK')}
            value={String(prescreen.candidate_k)}
            disabled={disabled}
            onChange={(e) =>
              setPrescreen({
                candidate_k: Math.max(
                  value.retrieval.chunks,
                  Number(e.target.value) || value.retrieval.chunks,
                ),
              })
            }
          />
          <Input
            type="number"
            min={1}
            label={tr('prescreen.maxKeep')}
            value={String(prescreen.max_keep)}
            disabled={disabled}
            onChange={(e) =>
              setPrescreen({
                max_keep: Math.min(
                  prescreen.candidate_k,
                  Math.max(1, Number(e.target.value) || 1),
                ),
              })
            }
          />
          <Input
            type="number"
            min={1}
            label={tr('prescreen.batchSize')}
            value={String(prescreen.batch_size)}
            disabled={disabled}
            onChange={(e) =>
              setPrescreen({
                batch_size: Math.max(1, Number(e.target.value) || 1),
              })
            }
          />
        </div>
      )}
    </div>
  );

  const body = (
    <div className="flex flex-col gap-6">
      {/* Retrieval group (live) */}
      <div className="flex flex-col gap-3">
        <GroupHeader title={tr('retrieval.title')} tag={tr('retrieval.tag')} />

        <SettingRows>
          <SettingRow
            label={tr('retrieval.retriever')}
            htmlFor="retrieval-retriever"
            description={tr('retrieval.retrieverHint')}
            alignStart
          >
            <Select
              value={value.retrieval.retriever}
              disabled={disabled}
              onValueChange={(v) => setRetrieval({ retriever: v })}
            >
              <SelectTrigger
                id="retrieval-retriever"
                className="w-52"
                size="field"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {retrievers.map((r) => (
                  <SelectItem key={r} value={r}>
                    {tr(`retrieval.retrievers.${r}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </SettingRow>

          <SettingRow label={tr('retrieval.chunks')} htmlFor="retrieval-chunks">
            <Input
              id="retrieval-chunks"
              type="number"
              min={1}
              className="w-24 text-right"
              value={String(value.retrieval.chunks)}
              disabled={disabled}
              onChange={(e) =>
                setRetrieval({
                  chunks: Math.max(1, Number(e.target.value) || 1),
                })
              }
            />
          </SettingRow>

          {/* Rephrasing only fires when there is chat history to rephrase
              against, and a test has none — so the switch would do nothing. */}
          {!queryOnly && (
            <SettingRow
              label={tr('retrieval.rephraseQuery')}
              htmlFor="retrieval-rephrase"
            >
              <Switch
                id="retrieval-rephrase"
                checked={value.retrieval.rephrase_query}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  setRetrieval({ rephrase_query: checked })
                }
              />
            </SettingRow>
          )}

          {!queryOnly && linksAvailable && (
            <SettingRow
              label={tr('retrieval.showLinks')}
              htmlFor="retrieval-show-links"
              description={tr('retrieval.showLinksHint')}
              alignStart
            >
              <Switch
                id="retrieval-show-links"
                checked={value.retrieval.show_links}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  setRetrieval({ show_links: checked })
                }
              />
            </SettingRow>
          )}

          {!queryOnly && (
            <SettingRow
              label={tr('retrieval.exposure')}
              htmlFor="retrieval-exposure"
              description={tr('retrieval.exposureHint')}
              alignStart
            >
              <Select
                value={value.retrieval.exposure}
                disabled={disabled}
                onValueChange={(v) =>
                  setRetrieval({ exposure: v as RetrievalExposure })
                }
              >
                <SelectTrigger
                  id="retrieval-exposure"
                  className="w-52"
                  size="field"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="prefetch">
                    {tr('retrieval.exposures.prefetch')}
                  </SelectItem>
                  <SelectItem value="agentic_tool">
                    {tr('retrieval.exposures.agentic_tool')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>
          )}
        </SettingRows>
      </div>

      {relevanceGroup}

      {/* Advanced (live): the exact relevance, its candidates, the similarity
          threshold and LLM screening. No gap on the wrapper: a closed
          Collapsible is still a flex item (DESIGN.md › Disclosure). */}
      <div className="flex flex-col">
        <CollapsibleTrigger
          open={advancedOpen}
          onOpenChange={() => setAdvancedToggled(!advancedOpen)}
          controls={advancedId}
          chevron="sm"
        >
          <span>{tr('advanced')}</span>
        </CollapsibleTrigger>
        <Collapsible open={advancedOpen} id={advancedId}>
          <div className="pt-3">{advancedRows}</div>
        </Collapsible>
      </div>

      {/* Graph retrieval group (graphrag only; live, so shown when testing too) */}
      {isGraphRAG && (
        <div className="flex flex-col gap-3">
          <GroupHeader
            title={tr('graphRetrieval.title')}
            tag={tr('graphRetrieval.tag')}
          />
          <p className="text-muted-foreground text-xs">
            {tr('graphRetrieval.agentToolHint')}
          </p>

          <SettingRows>
            <SettingRow
              label={tr('graphRetrieval.seedStrategy')}
              htmlFor="graph-seed-strategy"
              description={tr('graphRetrieval.seedStrategyHint')}
              alignStart
            >
              <Select
                value={value.retrieval.graph.seed_strategy}
                disabled={disabled}
                onValueChange={(v) =>
                  setGraphRetrieval({ seed_strategy: v as GraphSeedStrategy })
                }
              >
                <SelectTrigger
                  id="graph-seed-strategy"
                  className="w-52"
                  size="field"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="entities">
                    {tr('graphRetrieval.seedEntities')}
                  </SelectItem>
                  <SelectItem value="relationships">
                    {tr('graphRetrieval.seedRelationships')}
                  </SelectItem>
                </SelectContent>
              </Select>
            </SettingRow>

            <SettingRow
              label={tr('graphRetrieval.passageNodes')}
              htmlFor="graph-passage-nodes"
              description={tr('graphRetrieval.passageNodesHint')}
              alignStart
            >
              <Switch
                id="graph-passage-nodes"
                checked={value.retrieval.graph.passage_nodes}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  setGraphRetrieval({ passage_nodes: checked })
                }
              />
            </SettingRow>

            <SettingRow
              label={tr('graphRetrieval.blendVector')}
              htmlFor="graph-blend-vector"
              description={tr('graphRetrieval.blendVectorHint')}
              alignStart
            >
              <Switch
                id="graph-blend-vector"
                checked={value.retrieval.graph.blend_vector}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  setGraphRetrieval({ blend_vector: checked })
                }
              />
            </SettingRow>
          </SettingRows>
        </div>
      )}

      {/* Graph extraction group (graphrag only; re-ingest required to apply) */}
      {isGraphRAG && !ingestHidden && (
        <div className="flex flex-col gap-3">
          <GroupHeader title={tr('graph.title')} tag={tr('graph.tag')} />

          <SettingRows>
            <SettingRow
              label={tr('graph.extractionModel')}
              htmlFor="graph-extraction-model"
              description={tr('graph.extractionModelHint')}
              alignStart
            >
              <Select
                value={value.graph.extraction_model ?? GRAPH_DEFAULT_MODEL}
                disabled={disabled}
                onValueChange={(v) =>
                  setGraph({
                    extraction_model: v === GRAPH_DEFAULT_MODEL ? null : v,
                  })
                }
              >
                <SelectTrigger
                  id="graph-extraction-model"
                  className="w-52"
                  size="field"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={GRAPH_DEFAULT_MODEL}>
                    {tr('graph.defaultModel')}
                  </SelectItem>
                  {modelOptions.builtin.map((m) => (
                    <SelectItem key={`builtin-${m.id}`} value={m.id}>
                      {m.display_name}
                    </SelectItem>
                  ))}
                  {modelOptions.user.map((m) => (
                    <SelectItem key={`user-${m.id}`} value={m.id}>
                      {m.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </SettingRow>

            <SettingRow
              label={tr('graph.maxChunks')}
              htmlFor="graph-max-chunks"
              description={tr('graph.maxChunksHint')}
              alignStart
            >
              <Input
                id="graph-max-chunks"
                type="number"
                min={1}
                className="w-24 text-right"
                value={
                  value.graph.max_chunks === null
                    ? ''
                    : String(value.graph.max_chunks)
                }
                disabled={disabled}
                placeholder={tr('graph.maxChunksPlaceholder')}
                onChange={(e) => {
                  const raw = e.target.value;
                  setGraph({
                    max_chunks:
                      raw === '' ? null : Math.max(1, Number(raw) || 1),
                  });
                }}
              />
            </SettingRow>
          </SettingRows>
        </div>
      )}

      {/* Chunking group (re-ingest required) */}
      <div className={cn('flex flex-col gap-3', ingestHidden && 'hidden')}>
        <GroupHeader title={tr('chunking.title')} tag={tr('chunking.tag')} />

        <SettingRows>
          <SettingRow
            label={tr('chunking.strategy')}
            htmlFor="chunking-strategy"
          >
            <Select
              value={value.chunking.strategy}
              disabled={disabled}
              onValueChange={(v) =>
                setChunking({ strategy: v as ChunkingStrategy })
              }
            >
              <SelectTrigger
                id="chunking-strategy"
                className="w-52"
                size="field"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {strategyOptions.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </SettingRow>

          <SettingRow
            label={tr('chunking.maxTokens')}
            description={tr('chunking.maxTokensHint')}
            htmlFor="chunking-max-tokens"
          >
            <Input
              id="chunking-max-tokens"
              type="number"
              min={1}
              max={MAX_CHUNK_TOKENS}
              className="w-24 text-right"
              value={String(value.chunking.max_tokens)}
              disabled={disabled}
              onChange={(e) =>
                setChunking({
                  max_tokens: clampChunkTokens(Number(e.target.value)),
                })
              }
            />
          </SettingRow>

          <SettingRow
            label={tr('chunking.minTokens')}
            htmlFor="chunking-min-tokens"
          >
            <Input
              id="chunking-min-tokens"
              type="number"
              min={0}
              className="w-24 text-right"
              value={String(value.chunking.min_tokens)}
              disabled={disabled}
              onChange={(e) =>
                setChunking({
                  min_tokens: Math.max(0, Number(e.target.value) || 0),
                })
              }
            />
          </SettingRow>

          <SettingRow
            label={tr('chunking.duplicateHeaders')}
            htmlFor="chunking-dup-headers"
          >
            <Switch
              id="chunking-dup-headers"
              checked={value.chunking.duplicate_headers}
              disabled={disabled}
              onCheckedChange={(checked) =>
                setChunking({ duplicate_headers: checked })
              }
            />
          </SettingRow>
        </SettingRows>
      </div>
    </div>
  );

  if (alwaysOpen) {
    return body;
  }

  return (
    // No gap here: a closed Collapsible is still a flex item, so the body
    // carries the space as top padding (DESIGN.md › Disclosure).
    <div className="flex flex-col">
      <CollapsibleTrigger
        open={expanded}
        onOpenChange={() => setOpen((o) => !o)}
        controls={bodyId}
        chevron="sm"
      >
        <span>{title ?? tr('title')}</span>
      </CollapsibleTrigger>
      <Collapsible open={expanded} id={bodyId}>
        <div className="pt-4">{body}</div>
      </Collapsible>
    </div>
  );
}
