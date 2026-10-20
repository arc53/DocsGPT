import { useState } from 'react';

import PageToolbar from '../components/PageToolbar';
import ConversationInsights, {
  InsightsIntro,
} from './insights/ConversationInsights';
import { insightsState } from './insights/format';
import { useConversationInsights } from './insights/useConversationInsights';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from './TimeFilterSelect';

/**
 * Settings › Insights: what the decision model estimated about every
 * agent's conversations, and the account's docs-gap report. Its own page
 * in the Monitoring group, next to Analytics and Logs. The description and
 * the window select are the page toolbar (PATTERNS › Page chrome), the
 * same slot as Settings › Analytics; the section under it opens with the
 * figures.
 */
export default function AccountInsights() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  const insights = useConversationInsights(undefined, timeFilter);
  const state = insightsState(insights.status, insights.data);
  // Off on the server: the section draws nothing, so neither does its page.
  if (state === 'serverOff') return null;
  return (
    <>
      <PageToolbar
        intro={<InsightsIntro state={state} data={insights.data} />}
        action={
          <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
        }
      />
      <ConversationInsights
        state={state}
        data={insights.data}
        filterOption={timeFilter}
        onRetry={insights.retry}
        standalone
        intro={false}
      />
    </>
  );
}
