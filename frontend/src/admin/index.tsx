import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import { useMediaQuery } from '../hooks';
import SectionIndexPage from '../navigation/SectionIndexPage';
import SectionPageHeader from '../navigation/SectionPageHeader';
import { ADMIN_SECTION, getActiveItem } from '../navigation/sections';
import Admins from './Admins';
import Audit from './Audit';
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
  const { isMobile, isTablet } = useMediaQuery();

  const activeItem = getActiveItem(ADMIN_SECTION, location.pathname);
  const showIndex =
    (isMobile || isTablet) && location.pathname === ADMIN_SECTION.rootPath;

  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className="mx-auto w-full max-w-7xl">
        {showIndex ? (
          <SectionIndexPage section={ADMIN_SECTION} />
        ) : (
          <>
            <SectionPageHeader section={ADMIN_SECTION} item={activeItem} />
            <Routes>
              <Route index element={<Overview />} />
              <Route path="overview" element={<Overview />} />
              <Route path="users" element={<Users />} />
              <Route path="roles" element={<Admins />} />
              <Route path="usage" element={<Usage />} />
              <Route path="quotas" element={<Quotas />} />
              <Route path="audit" element={<Audit />} />
              <Route path="*" element={<Navigate to="/admin" replace />} />
            </Routes>
          </>
        )}
      </div>
    </div>
  );
}
