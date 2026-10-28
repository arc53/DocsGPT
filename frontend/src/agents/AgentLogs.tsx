import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  useLocation,
  useNavigationType,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import {
  selectAnalyticsEnabled,
  selectToken,
} from '../preferences/preferenceSlice';
import type { AgentTopic } from '../settings/types';

import Logs from '../settings/Logs';
import { revealElement } from '../settings/logsLinks';
import { EmptyState } from '../components/ui/empty-state';
import { SectionHeader } from '../components/ui/section-header';
import SectionShell from '../navigation/SectionShell';
import AgentPageToolbar, { LastUsedMeta } from './components/AgentPageToolbar';
import GuardrailEvents from './components/GuardrailEvents';
import { useAgent } from './hooks/useAgent';

/**
 * An agent's Logs: its guardrail activity, then its log list under a Logs
 * heading. The usage charts
 * are its Analytics page (`AgentAnalytics`).
 */
export default function AgentLogs() {
  const { t } = useTranslation();
  const { agentId } = useParams();
  const { agent, error, reload } = useAgent(agentId);
  const location = useLocation();
  const navigationType = useNavigationType();
  const [searchParams] = useSearchParams();
  const logsRef = useRef<HTMLElement>(null);

  // A drill-down (a docs-gap example, "See every docs gap") lands on Logs
  // further down this page: bring it into view. The label select replaces
  // the entry instead, so changing the filter in place doesn't scroll.
  const label = searchParams.get('label');
  const conversation = searchParams.get('conversation');
  useEffect(() => {
    if (navigationType === 'REPLACE') return;
    if (!label && !conversation) return;
    revealElement(logsRef.current, 'start');
  }, [location.key, label, conversation, navigationType]);

  const analytics = agent?.config?.analytics;
  const enabled = analytics?.enabled !== false;
  const topics = useAgentTopics(agentId, Boolean(agent) && enabled);

  return (
    <SectionShell>
      {agent ? (
        <AgentPageToolbar
          name={agent.name}
          meta={<LastUsedMeta lastUsedAt={agent.last_used_at} />}
        />
      ) : (
        // The record only fills the byline (and the label filter's topics):
        // its failure stands in for the byline, and the guardrail activity
        // and logs below, which need only the id, stay.
        error && (
          <EmptyState
            tone="destructive"
            size="sm"
            illustration="none"
            title={t('agents.loadError')}
            onRetry={reload}
          />
        )
      )}
      {agentId && (
        <>
          <GuardrailEvents agentId={agentId} />
          {/* The drill-down target (`#logs`): a named section, the peer of
            Guardrail activity. */}
          <section ref={logsRef} id="logs" className="mt-8 scroll-mt-4">
            <SectionHeader
              title={t('agents.pageHeader.tabs.logs')}
              description={t('agents.logs.description')}
              className="mb-4"
            />
            <Logs
              agentId={agentId}
              analytics={
                agent
                  ? {
                      enabled,
                      topics,
                    }
                  : undefined
              }
            />
          </section>
        </>
      )}
    </SectionShell>
  );
}

/**
 * The agent's topics as Logs filters: its folders and own topics, which
 * only the server can list (`/api/analytics/topics`). Empty until they load,
 * while insights are off, and if the request fails.
 */
function useAgentTopics(
  agentId: string | undefined,
  enabled: boolean,
): AgentTopic[] {
  const token = useSelector(selectToken);
  const serverLabels = useSelector(selectAnalyticsEnabled);
  const [loaded, setLoaded] = useState<{
    agentId: string;
    topics: AgentTopic[];
  } | null>(null);
  const wanted = Boolean(agentId) && enabled && serverLabels;
  useEffect(() => {
    if (!wanted || !agentId) return;
    let cancelled = false;
    userService
      .getAgentTopics(agentId, token)
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { success?: boolean; topics?: AgentTopic[] } | null) => {
        if (!cancelled && body?.success)
          setLoaded({ agentId, topics: body.topics ?? [] });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [wanted, agentId, token]);
  return wanted && loaded && loaded.agentId === agentId ? loaded.topics : [];
}
