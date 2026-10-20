import { useState } from 'react';

import { InsightsSection } from './insights/ConversationInsights';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from './TimeFilterSelect';

/**
 * Settings › Insights: what the decision model estimated about every
 * agent's conversations, and the account's docs-gap report. Its own page
 * in the Monitoring group, next to Analytics and Logs, like an agent's
 * Insights; the time window sits where Analytics has its own.
 */
export default function AccountInsights() {
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  return (
    <InsightsSection
      filterOption={timeFilter}
      standalone
      actions={<TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />}
    />
  );
}
