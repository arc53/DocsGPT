import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { useMediaQuery } from '../hooks';
import SectionIndexPage from '../navigation/SectionIndexPage';
import SectionShell from '../navigation/SectionShell';
import { ADMIN_SECTION } from '../navigation/sections';
import Admins from './Admins';
import Activity from './Activity';
import Overview from './Overview';
import Quotas from './Quotas';
import Usage from './Usage';
import Users from './Users';

/**
 * Admin dashboard (operator-level, global admin). Reached only via <AdminRoute>
 * (cosmetic guard); every endpoint it calls is independently @admin_required on
 * the server. Navigation lives in the sidebar, like the settings section.
 */
export default function Admin() {
  const location = useLocation();
  const { isMobile } = useMediaQuery();

  const showIndex = isMobile && location.pathname === ADMIN_SECTION.rootPath;

  if (showIndex) {
    return (
      <SectionShell width="wide" header={false}>
        <SectionIndexPage section={ADMIN_SECTION} />
      </SectionShell>
    );
  }

  return (
    <SectionShell width="wide">
      <Routes>
        <Route index element={<Overview />} />
        <Route path="overview" element={<Overview />} />
        <Route path="users" element={<Users />} />
        <Route path="roles" element={<Admins />} />
        <Route path="usage" element={<Usage />} />
        <Route path="quotas" element={<Quotas />} />
        <Route path="audit" element={<Activity />} />
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </SectionShell>
  );
}
