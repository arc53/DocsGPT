import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import {
  DEFAULT_GUARDRAILS,
  GuardrailsEditor,
  guardrailsIncomplete,
  useGuardrailCatalog,
} from '../agents/components/GuardrailsSection';
import type { GuardrailsConfig } from '../agents/types';
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
import { type InjectionModel, InjectionModelOff } from './injectionModel';

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

type SourceDefaultsBody = {
  success: boolean;
  retrieval: SourceRetrievalConfig;
  relevance_model: RelevanceModel;
};

type AgentDefaultsBody = {
  success: boolean;
  guardrails: GuardrailsConfig;
  injection_model: InjectionModel;
};

/** The form: the retrieval options and the new-agent guardrails. */
type Values = {
  retrieval: RetrievalOptionsValue;
  agentGuardrails: GuardrailsConfig;
};

const guardrailsOf = (body: AgentDefaultsBody): GuardrailsConfig => ({
  ...DEFAULT_GUARDRAILS,
  ...(body.guardrails ?? {}),
});

const valuesOf = (
  sources: SourceDefaultsBody,
  agents: AgentDefaultsBody,
): Values => ({
  retrieval: configToOptions({ retrieval: sources.retrieval }),
  agentGuardrails: guardrailsOf(agents),
});

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
 * Admin › Defaults: the settings a new source (retrieval) and a new agent
 * (guardrails) start with. They are copied in when the
 * source or agent is created; saving never changes an existing one.
 */
export default function Defaults() {
  const token = useSelector(selectToken);
  const { graphRAGAvailable, hybridAvailable, availableModels } =
    useRetrievalAvailability(token);
  const { catalog, loadError, retry } = useGuardrailCatalog(token);
  const [sources, setSources] = useState<SourceDefaultsBody | null>(null);
  const [agents, setAgents] = useState<AgentDefaultsBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState<Values | null>(null);
  const [value, setValue] = useState<Values | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // A section the admin edited while its save was pending keeps the edit;
  // only the saved baseline moves to the response.
  const settle = useCallback(
    <K extends keyof Values>(
      key: K,
      next: Values[K],
      unchanged: (current: Values[K]) => boolean,
    ) => {
      setSaved((current) => (current ? { ...current, [key]: next } : current));
      setValue((current) =>
        current && unchanged(current[key])
          ? { ...current, [key]: next }
          : current,
      );
    },
    [],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const [sourcesRes, agentsRes] = await Promise.all([
        adminService.getSourceDefaults(token),
        adminService.getAgentDefaults(token),
      ]);
      const sourcesBody = await sourcesRes.json().catch(() => null);
      const agentsBody = await agentsRes.json().catch(() => null);
      if (!sourcesBody?.success || !agentsBody?.success) {
        setFailed(true);
        return;
      }
      const values = valuesOf(sourcesBody, agentsBody);
      setSources(sourcesBody);
      setAgents(agentsBody);
      setSaved(values);
      setValue(values);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && value === null) return <LoadingState fill="block" />;
  if (failed || !sources || !agents || value === null || saved === null)
    return <LoadError message="Failed to load the defaults." onRetry={load} />;

  const retrieval = optionsToConfig(value.retrieval).retrieval ?? {};
  const retrievalChanged =
    JSON.stringify(retrieval) !==
    JSON.stringify(optionsToConfig(saved.retrieval).retrieval);
  const agentsChanged =
    JSON.stringify(value.agentGuardrails) !==
    JSON.stringify(saved.agentGuardrails);
  const valid =
    isPrescreenConfigValid(value.retrieval) &&
    !guardrailsIncomplete(value.agentGuardrails);

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    const failure = 'Could not save the defaults.';
    try {
      if (retrievalChanged) {
        const res = await adminService.setSourceDefaults(retrieval, token);
        const body = await res.json().catch(() => ({ success: false }));
        if (!body?.success) {
          setSaveError(body?.message || failure);
          return;
        }
        setSources(body);
        const sent = JSON.stringify(retrieval);
        settle(
          'retrieval',
          configToOptions({ retrieval: body.retrieval }),
          (current) =>
            JSON.stringify(optionsToConfig(current).retrieval ?? {}) === sent,
        );
      }
      if (agentsChanged) {
        const submitted = value.agentGuardrails;
        const res = await adminService.setAgentDefaults(submitted, token);
        const body = await res.json().catch(() => ({ success: false }));
        if (!body?.success) {
          setSaveError(body?.message || failure);
          return;
        }
        setAgents(body);
        settle(
          'agentGuardrails',
          guardrailsOf(body),
          (current) => JSON.stringify(current) === JSON.stringify(submitted),
        );
      }
    } catch {
      setSaveError(failure);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <PageToolbar
        intro="The settings new sources and new agents start with."
        action={
          <Button
            size="field"
            shape="pill"
            onClick={save}
            loading={saving}
            disabled={!(retrievalChanged || agentsChanged) || !valid}
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
        {!isPrescreenConfigValid(value.retrieval) && (
          <Alert variant="warning" className="mb-6">
            <AlertDescription>
              Check the LLM screening values: candidates to fetch must be at
              least the number of chunks, and chunks to keep must not exceed
              candidates to fetch.
            </AlertDescription>
          </Alert>
        )}
      </PageToolbar>
      <div className="flex flex-col gap-10">
        <section className="flex flex-col gap-8">
          <SectionHeader
            as="h2"
            title="New sources"
            description="Applies to sources created from now on. Existing sources keep their own settings."
          />
          <div className="flex flex-col gap-3">
            <SectionHeader size="xs" as="h3" title="Relevance model" />
            <RelevanceModelNotice model={sources.relevance_model} />
          </div>
          <RetrievalOptions
            value={value.retrieval}
            onChange={(next) => setValue({ ...value, retrieval: next })}
            alwaysOpen
            retrievalOnly
            hybridAvailable={hybridAvailable}
            graphRAGAvailable={graphRAGAvailable}
            availableModels={availableModels}
            decision={{ relevance: sources.relevance_model.enabled }}
          />
        </section>
        <section className="flex flex-col gap-5">
          <SectionHeader
            as="h2"
            title="New agents"
            description="Applies to agents created from now on. Existing agents keep their own guardrails."
          />
          {!agents.injection_model.enabled && <InjectionModelOff />}
          <GuardrailsEditor
            value={value.agentGuardrails}
            onChange={(agentGuardrails) =>
              setValue({ ...value, agentGuardrails })
            }
            catalog={catalog}
            loadError={loadError}
            onRetry={retry}
            enableDescription="Run the selected checks on a new agent's runs"
          />
        </section>
      </div>
    </div>
  );
}
