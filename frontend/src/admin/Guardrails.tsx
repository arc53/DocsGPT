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
import { Alert, AlertDescription } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { LoadingState } from '../components/ui/loading-state';
import { SectionHeader } from '../components/ui/section-header';
import { SettingRow, SettingRows } from '../components/ui/setting-row';
import { Switch } from '../components/ui/switch';
import { selectToken } from '../preferences/preferenceSlice';
import { LoadError } from './AdminUI';
import { type InjectionModel, InjectionModelNotice } from './injectionModel';

type GuardrailsBody = {
  success: boolean;
  floor: GuardrailsConfig | null;
  mcp_description_warnings: boolean;
  injection_model: InjectionModel;
};

type Settings = { floor: GuardrailsConfig; warnings: boolean };

const settingsOf = (body: GuardrailsBody): Settings => ({
  floor: { ...DEFAULT_GUARDRAILS, ...(body.floor ?? {}) },
  warnings: body.mcp_description_warnings,
});

/**
 * Admin › Guardrails: the rules every agent follows (the floor), existing
 * agents included, edited with the agent form's guardrails controls; whether
 * MCP tool descriptions are scored for prompt injection; and what the
 * prompt-injection model costs on this server.
 */
export default function Guardrails() {
  const token = useSelector(selectToken);
  const { catalog, loadError, retry } = useGuardrailCatalog(token);
  const [data, setData] = useState<GuardrailsBody | null>(null);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState<Settings | null>(null);
  const [value, setValue] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const apply = useCallback((body: GuardrailsBody) => {
    setData(body);
    setSaved(settingsOf(body));
    setValue(settingsOf(body));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminService.getGuardrails(token);
      const body = await res.json().catch(() => ({ success: false }));
      if (body?.success) apply(body);
      else setData({ success: false } as GuardrailsBody);
    } catch {
      setData({ success: false } as GuardrailsBody);
    } finally {
      setLoading(false);
    }
  }, [token, apply]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && data === null) return <LoadingState fill="block" />;
  if (!data?.success || value === null || saved === null)
    return (
      <LoadError message="Failed to load the guardrails." onRetry={load} />
    );

  const floorChanged =
    JSON.stringify(value.floor) !== JSON.stringify(saved.floor);
  const warningsChanged = value.warnings !== saved.warnings;
  const incomplete = guardrailsIncomplete(value.floor);

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await adminService.setGuardrails(
        {
          ...(floorChanged ? { floor: value.floor } : {}),
          ...(warningsChanged
            ? { mcp_description_warnings: value.warnings }
            : {}),
        },
        token,
      );
      const body = await res.json().catch(() => ({ success: false }));
      if (body?.success) {
        apply(body);
        // The catalog carries the floor the agent forms lock.
        retry();
      } else setSaveError(body?.message || 'Could not save the guardrails.');
    } catch {
      setSaveError('Could not save the guardrails.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-3xl">
      <PageToolbar
        intro="Rules every agent follows, existing agents included. An agent can add stricter controls but cannot remove these."
        action={
          <Button
            size="field"
            shape="pill"
            onClick={save}
            loading={saving}
            disabled={(!floorChanged && !warningsChanged) || incomplete}
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
      </PageToolbar>
      <div className="flex flex-col gap-8">
        <div className="flex flex-col gap-3">
          <SectionHeader size="xs" as="h2" title="Prompt-injection model" />
          <InjectionModelNotice model={data.injection_model} />
        </div>
        <div className="flex flex-col gap-3">
          <SectionHeader size="xs" as="h2" title="Rules every agent follows" />
          <GuardrailsEditor
            value={value.floor}
            onChange={(floor) => setValue({ ...value, floor })}
            catalog={catalog}
            loadError={loadError}
            onRetry={retry}
            showFloor={false}
            enableLabel="Apply these rules to every agent"
            enableDescription="Every agent runs the controls below on top of its own. Where an agent sets the same check and stage, these settings apply and the stricter action wins."
          />
        </div>
        <div className="flex flex-col gap-3">
          <SectionHeader size="xs" as="h2" title="MCP tools" />
          <SettingRows>
            <SettingRow
              label="Warn about tool descriptions that look like prompt injection"
              description="Scores each MCP server's action descriptions when it is saved or refreshed, and marks the suspicious actions in their permissions. Nothing is turned off."
              alignStart
            >
              <Switch
                checked={value.warnings}
                onCheckedChange={(warnings) => setValue({ ...value, warnings })}
                data-testid="mcp-description-warnings"
              />
            </SettingRow>
          </SettingRows>
        </div>
      </div>
    </div>
  );
}
