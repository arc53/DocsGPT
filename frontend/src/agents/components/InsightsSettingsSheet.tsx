import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  PanelBody,
  PanelFooter,
  PanelHeader,
  SidePanel,
} from '@/components/ui/side-panel';

import userService from '../../api/services/userService';
import { selectToken } from '../../preferences/preferenceSlice';
import { useAnalyticsAvailability } from '../../settings/insights/useAnalyticsAvailability';
import { analyticsOf, withAnalytics } from '../analyticsConfig';
import { isWorkflowAgent } from '../paths';
import type { Agent, AgentConfig, AnalyticsConfig } from '../types';
import InsightsSettingsBody from './InsightsSettingsBody';

type InsightsSettingsSheetProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The agent as saved: the draft starts from its `config.analytics`. */
  agent: Agent;
  /** Start with Collect insights switched on (Insights' "Turn on"). */
  startEnabled?: boolean;
  /** Receives the config as saved. */
  onSaved: (config: AgentConfig) => void;
};

/**
 * An agent's insights settings in a modal side panel, opened from its
 * Insights page (the toolbar's Settings, and Turn on while it is off). It
 * edits a draft of the saved settings and saves only `config.analytics`, on
 * top of the config as the server has it at that moment (read again just
 * before the save), so it never meets unsaved Overview edits (another route)
 * nor undoes a guardrails or allowlist change saved meanwhile. Cancel, the X,
 * Escape and the scrim drop the draft; while a save is out they do nothing.
 *
 * Args:
 *   open: Whether the panel is open.
 *   onOpenChange: Opens or closes it; it closes itself after a save.
 *   agent: The saved agent.
 *   startEnabled: Turn the draft on when it opens.
 *   onSaved: Gets the saved config, to refresh the page.
 */
export default function InsightsSettingsSheet({
  open,
  onOpenChange,
  agent,
  startEnabled = false,
  onSaved,
}: InsightsSettingsSheetProps) {
  // A save that is out holds the panel open: closed, its answer would land
  // on a panel opened again meanwhile.
  const saving = useRef(false);
  const handleOpenChange = (next: boolean) => {
    if (!next && saving.current) return;
    onOpenChange(next);
  };
  return (
    <SidePanel open={open} onOpenChange={handleOpenChange}>
      {/* Mounted only while open, so each opening starts a fresh draft and
          the limits and folders load only then. */}
      <SheetContents
        agent={agent}
        startEnabled={startEnabled}
        onClose={() => onOpenChange(false)}
        onSaved={onSaved}
        onSavingChange={(value) => {
          saving.current = value;
        }}
      />
    </SidePanel>
  );
}

function SheetContents({
  agent,
  startEnabled,
  onClose,
  onSaved,
  onSavingChange,
}: {
  agent: Agent;
  startEnabled: boolean;
  onClose: () => void;
  onSaved: (config: AgentConfig) => void;
  onSavingChange: (saving: boolean) => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const limits = useAnalyticsAvailability();
  const saved = analyticsOf(agent.config?.analytics);
  const [draft, setDraft] = useState<AnalyticsConfig>(() =>
    startEnabled ? { ...saved, enabled: true } : saved,
  );
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  // This opening of the panel: a save that answers after it closed hands
  // its config back but neither closes nor touches a later one.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    setFailed(false);
    onSavingChange(true);
    try {
      // The config replaces the stored one whole: start from the server's
      // copy as it is now, not as the page loaded it, so a change saved
      // meanwhile elsewhere stays. No fresh copy, no save.
      const current = await userService.getAgent(agent.id ?? '', token);
      if (!current.ok) throw new Error('read failed');
      const fresh = (await current.json()) as Agent;
      const config = withAnalytics(fresh.config, draft);
      const form = new FormData();
      form.append('config', JSON.stringify(config));
      const response = await userService.updateAgent(
        agent.id ?? '',
        form,
        token,
      );
      if (!response.ok) throw new Error('save failed');
      onSaved(config);
      if (mounted.current) onClose();
    } catch {
      if (mounted.current) setFailed(true);
    } finally {
      onSavingChange(false);
      if (mounted.current) setSaving(false);
    }
  };

  return (
    <>
      <PanelHeader
        title={t('settings.analytics.insights.settings.title')}
        description={agent.name}
      />
      <PanelBody>
        {failed && (
          <Alert variant="destructive">
            <AlertDescription>
              {t('settings.analytics.insights.settings.saveFailed')}
            </AlertDescription>
          </Alert>
        )}
        <InsightsSettingsBody
          value={draft}
          onChange={setDraft}
          agentId={agent.id || undefined}
          maxTopics={limits.maxTopics}
          maxOverlapping={limits.maxOverlapping}
          disabled={saving}
          token={token}
          // A workflow has no agent-level sources: its topics are its own list.
          topicSource={isWorkflowAgent(agent) ? 'none' : 'sources'}
        />
      </PanelBody>
      <PanelFooter>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          shape="pill"
          disabled={saving}
          onClick={onClose}
        >
          {t('agents.form.buttons.cancel')}
        </Button>
        <Button
          type="button"
          size="lg"
          shape="pill"
          disabled={!dirty}
          loading={saving}
          onClick={save}
        >
          {t('agents.form.buttons.save')}
        </Button>
      </PanelFooter>
    </>
  );
}
