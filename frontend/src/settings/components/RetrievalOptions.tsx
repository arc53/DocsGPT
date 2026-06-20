import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Switch } from '../../components/ui/switch';
import type {
  ChunkingStrategy,
  RetrievalExposure,
  SourceConfig,
} from '../../models/misc';

import ChevronRight from '../../assets/chevron-right.svg';

// Defaults mirror the backend SourceConfig
// (application/storage/db/source_config.py). A form seeded with these and sent
// verbatim reproduces today's behavior, so the backend's "absent == default"
// contract is preserved either way.
export const DEFAULT_PRESCREEN = {
  candidate_k: 40,
  model: null as string | null,
  batch_size: 10,
  max_keep: 8,
};

// Fully-populated form shape so every control is controlled. Prescreen is
// flattened into the form (with an `enabled` flag) and re-nested on serialize.
export type RetrievalOptionsValue = {
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
    prescreen: {
      enabled: boolean;
      candidate_k: number;
      model: string | null;
      batch_size: number;
      max_keep: number;
    };
  };
};

export const DEFAULT_RETRIEVAL_OPTIONS: RetrievalOptionsValue = {
  chunking: {
    strategy: 'classic_chunk',
    max_tokens: 1250,
    min_tokens: 150,
    duplicate_headers: false,
  },
  retrieval: {
    retriever: 'classic',
    exposure: 'prefetch',
    chunks: 2,
    score_threshold: null,
    rephrase_query: true,
    prescreen: {
      enabled: false,
      ...DEFAULT_PRESCREEN,
    },
  },
};

const CHUNKING_STRATEGIES: ChunkingStrategy[] = [
  'classic_chunk',
  'recursive',
  'markdown',
  'parent_child',
];

/**
 * Hydrate the form value from a stored (possibly partial/absent) SourceConfig,
 * filling every missing field with the documented default. Lenient on read so a
 * legacy `{}` row produces an all-defaults form.
 */
export function configToOptions(config?: SourceConfig): RetrievalOptionsValue {
  const chunking = config?.chunking ?? {};
  const retrieval = config?.retrieval ?? {};
  const prescreen = retrieval.prescreen ?? null;
  const d = DEFAULT_RETRIEVAL_OPTIONS;
  return {
    chunking: {
      strategy: chunking.strategy ?? d.chunking.strategy,
      max_tokens: chunking.max_tokens ?? d.chunking.max_tokens,
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
      prescreen: {
        enabled: prescreen != null,
        candidate_k: prescreen?.candidate_k ?? DEFAULT_PRESCREEN.candidate_k,
        model: prescreen?.model ?? DEFAULT_PRESCREEN.model,
        batch_size: prescreen?.batch_size ?? DEFAULT_PRESCREEN.batch_size,
        max_keep: prescreen?.max_keep ?? DEFAULT_PRESCREEN.max_keep,
      },
    },
  };
}

/**
 * Serialize the form value into a full SourceConfig object the backend accepts.
 * The backend uses `extra="forbid"` and re-validates the whole object, so we
 * always send the complete (kind + chunking + retrieval) shape. Prescreen is
 * re-nested to `null` when disabled.
 */
export function optionsToConfig(value: RetrievalOptionsValue): SourceConfig {
  const ps = value.retrieval.prescreen;
  return {
    kind: 'classic',
    chunking: {
      strategy: value.chunking.strategy,
      max_tokens: value.chunking.max_tokens,
      min_tokens: value.chunking.min_tokens,
      duplicate_headers: value.chunking.duplicate_headers,
    },
    retrieval: {
      retriever: value.retrieval.retriever,
      exposure: value.retrieval.exposure,
      chunks: value.retrieval.chunks,
      score_threshold: value.retrieval.score_threshold,
      rephrase_query: value.retrieval.rephrase_query,
      prescreen: ps.enabled
        ? {
            candidate_k: ps.candidate_k,
            model: ps.model?.trim() ? ps.model.trim() : null,
            batch_size: ps.batch_size,
            max_keep: ps.max_keep,
          }
        : null,
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
}: RetrievalOptionsProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const expanded = alwaysOpen || open;

  const strategyOptions = useMemo(
    () =>
      CHUNKING_STRATEGIES.map((s) => ({
        value: s,
        label: t(`settings.sources.retrievalOptions.chunking.strategies.${s}`),
      })),
    [t],
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

  const tr = (key: string) => t(`settings.sources.retrievalOptions.${key}`);

  const body = (
    <div className="flex flex-col gap-6">
      {/* Retrieval group (live) */}
      <div className="flex flex-col gap-4">
        <div>
          <h4 className="text-foreground text-sm font-semibold">
            {tr('retrieval.title')}
          </h4>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {tr('retrieval.note')}
          </p>
        </div>

        <Input
          type="number"
          min={1}
          label={tr('retrieval.chunks')}
          value={String(value.retrieval.chunks)}
          disabled={disabled}
          labelBgClassName="bg-card"
          onChange={(e) =>
            setRetrieval({ chunks: Math.max(1, Number(e.target.value) || 1) })
          }
        />

        <div className="flex flex-col gap-1.5">
          <Input
            type="number"
            step="0.01"
            label={tr('retrieval.scoreThreshold')}
            value={
              value.retrieval.score_threshold === null
                ? ''
                : String(value.retrieval.score_threshold)
            }
            disabled={disabled}
            labelBgClassName="bg-card"
            placeholder={tr('retrieval.scoreThresholdPlaceholder')}
            onChange={(e) => {
              const raw = e.target.value;
              setRetrieval({
                score_threshold: raw === '' ? null : Number(raw),
              });
            }}
          />
          <p className="text-muted-foreground text-xs">
            {tr('retrieval.scoreThresholdHint')}
          </p>
        </div>

        <div className="flex flex-row items-center justify-between gap-3">
          <Label htmlFor="retrieval-rephrase" className="text-foreground">
            {tr('retrieval.rephraseQuery')}
          </Label>
          <Switch
            id="retrieval-rephrase"
            checked={value.retrieval.rephrase_query}
            disabled={disabled}
            onCheckedChange={(checked) =>
              setRetrieval({ rephrase_query: checked })
            }
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="retrieval-retriever" className="text-foreground">
            {tr('retrieval.retriever')}
          </Label>
          <Select value="classic" disabled>
            <SelectTrigger
              id="retrieval-retriever"
              className="w-full rounded-md"
              size="lg"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="classic">
                {tr('retrieval.retrievers.classic')}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="retrieval-exposure" className="text-foreground">
            {tr('retrieval.exposure')}
          </Label>
          <Select
            value={value.retrieval.exposure}
            disabled={disabled}
            onValueChange={(v) =>
              setRetrieval({ exposure: v as RetrievalExposure })
            }
          >
            <SelectTrigger
              id="retrieval-exposure"
              className="w-full rounded-md"
              size="lg"
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
          <p className="text-muted-foreground text-xs">
            {tr('retrieval.exposureHint')}
          </p>
        </div>

        {/* Prescreen sub-group */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-row items-center justify-between gap-3">
            <Label htmlFor="retrieval-prescreen" className="text-foreground">
              {tr('prescreen.enable')}
            </Label>
            <Switch
              id="retrieval-prescreen"
              checked={value.retrieval.prescreen.enabled}
              disabled={disabled}
              onCheckedChange={(checked) => setPrescreen({ enabled: checked })}
            />
          </div>
          <p className="text-muted-foreground text-xs">
            {tr('prescreen.warning')}
          </p>
          {value.retrieval.prescreen.enabled && (
            <div className="border-border flex flex-col gap-4 rounded-lg border p-4">
              <Input
                type="number"
                min={value.retrieval.chunks}
                label={tr('prescreen.candidateK')}
                value={String(value.retrieval.prescreen.candidate_k)}
                disabled={disabled}
                labelBgClassName="bg-card"
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
                value={String(value.retrieval.prescreen.max_keep)}
                disabled={disabled}
                labelBgClassName="bg-card"
                onChange={(e) =>
                  setPrescreen({
                    max_keep: Math.min(
                      value.retrieval.prescreen.candidate_k,
                      Math.max(1, Number(e.target.value) || 1),
                    ),
                  })
                }
              />
              <Input
                type="number"
                min={1}
                label={tr('prescreen.batchSize')}
                value={String(value.retrieval.prescreen.batch_size)}
                disabled={disabled}
                labelBgClassName="bg-card"
                onChange={(e) =>
                  setPrescreen({
                    batch_size: Math.max(1, Number(e.target.value) || 1),
                  })
                }
              />
              <Input
                type="text"
                label={tr('prescreen.model')}
                value={value.retrieval.prescreen.model ?? ''}
                disabled={disabled}
                labelBgClassName="bg-card"
                placeholder={tr('prescreen.modelPlaceholder')}
                onChange={(e) =>
                  setPrescreen({ model: e.target.value || null })
                }
              />
            </div>
          )}
        </div>
      </div>

      <hr className="border-border/60" />

      {/* Chunking group (re-ingest required) */}
      <div className="flex flex-col gap-4">
        <div>
          <h4 className="text-foreground text-sm font-semibold">
            {tr('chunking.title')}
          </h4>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {tr('chunking.note')}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="chunking-strategy" className="text-foreground">
            {tr('chunking.strategy')}
          </Label>
          <Select
            value={value.chunking.strategy}
            disabled={disabled}
            onValueChange={(v) =>
              setChunking({ strategy: v as ChunkingStrategy })
            }
          >
            <SelectTrigger
              id="chunking-strategy"
              className="w-full rounded-md"
              size="lg"
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
        </div>

        <Input
          type="number"
          min={1}
          label={tr('chunking.maxTokens')}
          value={String(value.chunking.max_tokens)}
          disabled={disabled}
          labelBgClassName="bg-card"
          onChange={(e) =>
            setChunking({
              max_tokens: Math.max(1, Number(e.target.value) || 1),
            })
          }
        />
        <Input
          type="number"
          min={0}
          label={tr('chunking.minTokens')}
          value={String(value.chunking.min_tokens)}
          disabled={disabled}
          labelBgClassName="bg-card"
          onChange={(e) =>
            setChunking({
              min_tokens: Math.max(0, Number(e.target.value) || 0),
            })
          }
        />
        <div className="flex flex-row items-center justify-between gap-3">
          <Label htmlFor="chunking-dup-headers" className="text-foreground">
            {tr('chunking.duplicateHeaders')}
          </Label>
          <Switch
            id="chunking-dup-headers"
            checked={value.chunking.duplicate_headers}
            disabled={disabled}
            onCheckedChange={(checked) =>
              setChunking({ duplicate_headers: checked })
            }
          />
        </div>
      </div>
    </div>
  );

  if (alwaysOpen) {
    return body;
  }

  return (
    <div className="flex flex-col gap-4">
      <Button
        type="button"
        variant="link"
        onClick={() => setOpen((o) => !o)}
        className="h-auto w-fit justify-start px-0 py-2 text-sm font-normal hover:no-underline"
      >
        <img
          src={ChevronRight}
          alt=""
          className={`h-3 w-3 transform transition-transform ${
            expanded ? 'rotate-90' : ''
          }`}
        />
        <span>{tr('title')}</span>
      </Button>
      <div
        className={`grid transition-all duration-300 ease-in-out ${
          expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
        }`}
      >
        <div className="overflow-hidden">{body}</div>
      </div>
    </div>
  );
}
