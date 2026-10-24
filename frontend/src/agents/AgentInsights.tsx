import { Settings2 } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useParams } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';

import SectionShell from '../navigation/SectionShell';
import ConversationInsights from '../settings/insights/ConversationInsights';
import { insightsState } from '../settings/insights/format';
import { useConversationInsights } from '../settings/insights/useConversationInsights';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from '../settings/TimeFilterSelect';
import { canAgent } from './agentAccess';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import InsightsSettingsSheet from './components/InsightsSettingsSheet';
import { useAgent } from './hooks/useAgent';
import { useAgentMenu } from './hooks/useAgentMenu';
import { agentLogsPath } from './paths';

/**
 * An agent's Insights: what the decision model estimated about
 * its conversations, and the docs-gap report. The weekly docs-gaps
 * notification links here (`#docs-gaps`); while the server has insights off,
 * such a link goes on to the agent's Logs. Whoever can edit the agent opens
 * its insights settings here, in a panel (Settings, or Turn on while off).
 */
export default function AgentInsights() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const { agent, error, reload, setAgent } = useAgent(agentId);
  const agentMenu = useAgentMenu({ agent });
  const [settings, setSettings] = useState<{
    open: boolean;
    startEnabled: boolean;
  }>({ open: false, startEnabled: false });
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  const insights = useConversationInsights(agentId, timeFilter);
  const state = insightsState(insights.status, insights.data);

  const canEdit = canAgent(agent, 'edit');
  const openSettings = (startEnabled: boolean) =>
    setSettings({ open: true, startEnabled });

  if (state === 'serverOff')
    return <Navigate to={agentLogsPath(agentId)} replace />;

  return (
    <SectionShell>
      <AgentPageToolbar
        name={agent?.name}
        meta={agent && <LastUsedMeta lastUsedAt={agent.last_used_at} />}
        actions={
          <div className="flex w-full gap-2 sm:w-auto">
            <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
            {canEdit && (
              <Button
                type="button"
                variant="outline"
                size="field"
                shape="pill"
                onClick={() => openSettings(false)}
              >
                <Settings2 />
                {t('settings.analytics.insights.settings.button')}
              </Button>
            )}
          </div>
        }
        menu={agentMenu.menu}
      />
      {agentMenu.modals}
      {error ? (
        <EmptyState
          tone="destructive"
          size="sm"
          illustration="none"
          title={t('agents.loadError')}
          onRetry={reload}
        />
      ) : (
        agentId && (
          <ConversationInsights
            state={state}
            data={insights.data}
            agentId={agentId}
            agent={agent}
            filterOption={timeFilter}
            onRetry={insights.retry}
            onTurnOn={canEdit ? () => openSettings(true) : undefined}
            onSetUpTopics={canEdit ? () => openSettings(false) : undefined}
          />
        )
      )}
      {agent && canEdit && (
        <InsightsSettingsSheet
          open={settings.open}
          onOpenChange={(open) => setSettings((prev) => ({ ...prev, open }))}
          agent={agent}
          startEnabled={settings.startEnabled}
          onSaved={(config) => {
            setAgent((prev) => ({ ...prev, config }));
            reload();
            insights.retry();
          }}
        />
      )}
    </SectionShell>
  );
}
