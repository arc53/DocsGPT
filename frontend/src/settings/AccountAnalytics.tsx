import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import PageToolbar from '../components/PageToolbar';
import Analytics from './Analytics';
import UsageQuota from './components/UsageQuota';
import TimeFilterSelect, {
  DEFAULT_TIME_FILTER,
  type TimeFilter,
} from './TimeFilterSelect';

/**
 * Settings › Analytics: the account's usage. The intro and the window select
 * are the page toolbar (PATTERNS › Page chrome), above the usage quota and
 * the charts, the same slot Settings › Insights uses.
 */
export default function AccountAnalytics() {
  const { t } = useTranslation();
  const [timeFilter, setTimeFilter] = useState<TimeFilter>(DEFAULT_TIME_FILTER);
  return (
    <>
      <PageToolbar
        intro={t('settings.analytics.subtitle')}
        action={
          <TimeFilterSelect value={timeFilter} onChange={setTimeFilter} />
        }
      />
      <UsageQuota />
      <Analytics filterOption={timeFilter} />
    </>
  );
}
