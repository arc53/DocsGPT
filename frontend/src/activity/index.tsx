import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { useMediaQuery } from '../hooks';
import Monitors from '../monitors/Monitors';
import SectionIndexPage from '../navigation/SectionIndexPage';
import SectionShell from '../navigation/SectionShell';
import { ACTIVITY_SECTION } from '../navigation/sections';
import AllSchedules from './AllSchedules';
import Calendar from './Calendar';
import History from './History';
import Now from './Now';
import { ACTIVITY_ROOT } from './paths';

/**
 * Activity shell. The destinations live in the sidebar (see
 * `navigation/SectionNav`); below `lg` the section root lists them as page
 * content instead, as Settings does.
 */
export default function Activity() {
  const location = useLocation();
  const { isMobile } = useMediaQuery();

  if (isMobile && location.pathname === ACTIVITY_SECTION.rootPath) {
    return (
      <SectionShell header={false}>
        <SectionIndexPage section={ACTIVITY_SECTION} />
      </SectionShell>
    );
  }

  return (
    <SectionShell>
      <Routes>
        <Route index element={<Now />} />
        <Route path="now" element={<Now />} />
        <Route path="calendar" element={<Calendar />} />
        <Route path="history" element={<History />} />
        <Route path="schedules" element={<AllSchedules />} />
        <Route path="monitors" element={<Monitors />} />
        <Route path="*" element={<Navigate to={ACTIVITY_ROOT} replace />} />
      </Routes>
    </SectionShell>
  );
}
