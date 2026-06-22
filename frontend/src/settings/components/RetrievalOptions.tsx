import { type ReactNode, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';

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
  'semantic',
];

const RETRIEVERS = ['classic', 'hybrid'];

/**
 * Group eyebrow: an uppercase, tracked title with a normal-weight muted ` · tag`
 * suffix. Reads as more prominent than the individual field labels below it.
 */
function GroupHeader({ title, tag }: { title: string; tag: string }) {
  return (
    <h4 className="text-foreground text-xs font-semibold tracking-wider uppercase">
      {title}
      <span className="text-muted-foreground font-normal normal-case">
        {' · '}
        {tag}
      </span>
    </h4>
  );
}

/**
 * One settings row: a left block (medium-weight label plus optional muted
 * description) and a right block holding the control. `alignStart` top-aligns
 * the row for controls paired with a multi-line description; otherwise both
 * sides are vertically centered.
 */
function SettingRow({
  label,
  htmlFor,
  description,
  alignStart = false,
  children,
}: {
  label: string;
  htmlFor?: string;
  description?: ReactNode;
  alignStart?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        'flex flex-row justify-between gap-4 py-3 first:pt-0 last:pb-0',
        alignStart ? 'items-start' : 'items-center',
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <Label
          htmlFor={htmlFor}
          className="text-foreground pointer-events-none w-fit text-sm font-medium"
        >
          {label}
        </Label>
        {description ? (
          <p className="text-muted-foreground text-xs">{description}</p>
        ) : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
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
      <div className="flex flex-col gap-3">
        <GroupHeader title={tr('retrieval.title')} tag={tr('retrieval.tag')} />

        <div className="divide-border/50 divide-y">
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
                className="w-52 rounded-md"
                size="lg"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RETRIEVERS.map((r) => (
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

          <SettingRow
            label={tr('retrieval.scoreThreshold')}
            htmlFor="retrieval-score-threshold"
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
              placeholder={tr('retrieval.scoreThresholdPlaceholder')}
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
                className="w-52 rounded-md"
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
          </SettingRow>

          <SettingRow
            label={tr('prescreen.enable')}
            htmlFor="retrieval-prescreen"
            description={tr('prescreen.warning')}
            alignStart
          >
            <Switch
              id="retrieval-prescreen"
              checked={value.retrieval.prescreen.enabled}
              disabled={disabled}
              onCheckedChange={(checked) => setPrescreen({ enabled: checked })}
            />
          </SettingRow>
        </div>

        {/* Prescreen expanded inputs (kept as floating-label cards) */}
        {value.retrieval.prescreen.enabled && (
          <div className="border-border ml-4 flex flex-col gap-4 rounded-lg border p-4">
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
          </div>
        )}
      </div>

      {/* Chunking group (re-ingest required) */}
      <div className="flex flex-col gap-3">
        <GroupHeader title={tr('chunking.title')} tag={tr('chunking.tag')} />

        <div className="divide-border/50 divide-y">
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
                className="w-52 rounded-md"
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
          </SettingRow>

          <SettingRow
            label={tr('chunking.maxTokens')}
            htmlFor="chunking-max-tokens"
          >
            <Input
              id="chunking-max-tokens"
              type="number"
              min={1}
              className="w-24 text-right"
              value={String(value.chunking.max_tokens)}
              disabled={disabled}
              onChange={(e) =>
                setChunking({
                  max_tokens: Math.max(1, Number(e.target.value) || 1),
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
        className="text-foreground hover:text-foreground h-auto w-fit justify-start px-0 py-2 text-sm font-normal hover:no-underline"
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
