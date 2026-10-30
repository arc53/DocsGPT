import { useState } from 'react';
import { Navigate } from 'react-router-dom';

import PageToolbar from '../components/PageToolbar';
import ConversationInsights, {
  InsightsIntro,
} from './insights/ConversationInsights';
import { insightsState, showsFigures } from './insights/format';
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
 * figures, and the description shows only above them.
 */
export default function AccountInsights() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  const insights = useConversationInsights(undefined, timeFilter);
  const state = insightsState(insights.status, insights.data);
  // Off on the server: nothing to show here, so a deep link (the weekly
  // notification's) goes on to Analytics.
  if (state === 'serverOff')
    return <Navigate to="/settings/analytics" replace />;
  return (
    <>
      <PageToolbar
        // Only above figures: an empty state says what it is itself.
        intro={
          showsFigures(state) ? (
            <InsightsIntro state={state} data={insights.data} />
          ) : undefined
        }
        action={
          <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
        }
      />
      <ConversationInsights
        state={state}
        data={insights.data}
        filterOption={timeFilter}
        onRetry={insights.retry}
        intro={false}
      />
    </>
  );
}
