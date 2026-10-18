import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import PageToolbar from '../components/PageToolbar';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { LoadingState } from '../components/ui/loading-state';
import { SectionHeader } from '../components/ui/section-header';
import type { SourceRetrievalConfig } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import RetrievalOptions, {
  configToOptions,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from '../settings/components/RetrievalOptions';
import useRetrievalAvailability from '../settings/components/useRetrievalAvailability';
import { LoadError } from './AdminUI';

/** What the relevance model costs here, as GET /api/admin/defaults/sources reports it. */
export type RelevanceModel = {
  enabled: boolean;
  // One relevance call over `candidate_k` chunks on this server; null until
  // the model has been measured.
  predicted_s: number | null;
  timeout_s: number;
  candidate_k: number;
  runtime: string | null;
};

type DefaultsBody = {
  success: boolean;
  retrieval: SourceRetrievalConfig;
  relevance_model: RelevanceModel;
};

const fmtSeconds = (s: number) => `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;

/**
 * The relevance model's cost on this server and, when a call would outlast
 * its deadline, the warning that it falls back to retriever order; or, while
 * the model is off, how the administrator turns it on.
 */
export function RelevanceModelNotice({ model }: { model: RelevanceModel }) {
  if (!model.enabled)
    return (
      <Alert variant="info" role="note">
        <AlertDescription>
          The relevance model is off on this server, so new sources get no
          relevance settings. Turn it on with{' '}
          <code className="font-mono">DECISION_RELEVANCE_ENABLED=true</code> in
          the server&apos;s environment.
        </AlertDescription>
      </Alert>
    );
  const predicted = model.predicted_s;
  const runtime = model.runtime ? `, ${model.runtime}` : '';
  return (
    <div className="flex flex-col gap-3">
      <Alert variant="info" role="note">
        <AlertDescription>
          {predicted === null
            ? 'Cost per answer on this server: measured after the model loads.'
            : `Adds about ${fmtSeconds(predicted)} per answer on this server (${model.candidate_k} candidates${runtime}).`}
        </AlertDescription>
      </Alert>
      {predicted !== null && predicted > model.timeout_s && (
        <Alert variant="warning">
          <AlertTitle>Relevance will time out on this server</AlertTitle>
          <AlertDescription>
            A call takes longer than its {fmtSeconds(model.timeout_s)} timeout,
            so answers fall back to the retriever&apos;s order. Raise{' '}
            <code className="font-mono">DECISION_RELEVANCE_TIMEOUT</code>, or
            run the model on a GPU or a decision server.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/**
 * Admin › Defaults: the retrieval settings a new source starts with. They are
 * copied into a source when it is created; saving never changes an existing
 * source.
 */
export default function Defaults() {
  const token = useSelector(selectToken);
  const { graphRAGAvailable, hybridAvailable, availableModels } =
    useRetrievalAvailability(token);
  const [data, setData] = useState<DefaultsBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState<RetrievalOptionsValue | null>(null);
  const [value, setValue] = useState<RetrievalOptionsValue | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const apply = useCallback((body: DefaultsBody) => {
    const options = configToOptions({ retrieval: body.retrieval });
    setData(body);
    setSaved(options);
    setValue(options);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminService.getSourceDefaults(token);
      const body = await res.json().catch(() => ({ success: false }));
      if (body?.success) apply(body);
      else setData({ success: false } as DefaultsBody);
    } catch {
      setData({ success: false } as DefaultsBody);
    } finally {
      setLoading(false);
    }
  }, [token, apply]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && data === null) return <LoadingState fill="block" />;
  if (!data?.success || value === null || saved === null)
    return <LoadError message="Failed to load the defaults." onRetry={load} />;

  const retrieval = optionsToConfig(value).retrieval ?? {};
  const changed =
    JSON.stringify(retrieval) !==
    JSON.stringify(optionsToConfig(saved).retrieval);
  const valid = isPrescreenConfigValid(value);

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await adminService.setSourceDefaults(retrieval, token);
      const body = await res.json().catch(() => ({ success: false }));
      if (body?.success) apply(body);
      else setSaveError(body?.message || 'Could not save the defaults.');
    } catch {
      setSaveError('Could not save the defaults.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <PageToolbar
        intro="Default retrieval settings for new sources. Applies to sources created from now on. Existing sources keep their own settings."
        action={
          <Button
            size="field"
            shape="pill"
            onClick={save}
            loading={saving}
            disabled={!changed || !valid}
            className="w-full sm:w-auto"
          >
            Save
          </Button>
        }
        divider
      >
        {saveError && (
          <Alert variant="destructive" className="mb-6">
            <AlertDescription>{saveError}</AlertDescription>
          </Alert>
        )}
        {!valid && (
          <Alert variant="warning" className="mb-6">
            <AlertDescription>
              Check the LLM screening values: candidates to fetch must be at
              least the number of chunks, and chunks to keep must not exceed
              candidates to fetch.
            </AlertDescription>
          </Alert>
        )}
      </PageToolbar>
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-3">
          <SectionHeader size="xs" as="h2" title="Relevance model" />
          <RelevanceModelNotice model={data.relevance_model} />
        </div>
        <RetrievalOptions
          value={value}
          onChange={setValue}
          alwaysOpen
          retrievalOnly
          hybridAvailable={hybridAvailable}
          graphRAGAvailable={graphRAGAvailable}
          availableModels={availableModels}
          decision={{ relevance: data.relevance_model.enabled }}
        />
      </div>
    </div>
  );
}
