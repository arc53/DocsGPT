import { useTranslation } from 'react-i18next';
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';

import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';
import Admins from './Admins';
import Audit from './Audit';
import Overview from './Overview';
import Usage from './Usage';
import Users from './Users';

const TABS = [
  { key: 'overview', label: 'Overview', path: '/admin' },
  { key: 'users', label: 'Users', path: '/admin/users' },
  { key: 'admins', label: 'Admins', path: '/admin/admins' },
  { key: 'usage', label: 'Usage', path: '/admin/usage' },
  { key: 'audit', label: 'Audit', path: '/admin/audit' },
];

/**
 * Admin dashboard (operator-level, global admin). Reached only via <AdminRoute>
 * (cosmetic guard); every endpoint it calls is independently @admin_required on
 * the server.
 */
export default function Admin() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const active =
    TABS.slice(1).find((tab) => location.pathname.startsWith(tab.path))
      ?.label ?? 'Overview';

  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <div className="mx-auto w-full max-w-7xl">
        <p className="text-foreground text-2xl font-bold">
          {t('admin.label', 'Admin')}
        </p>
        <Tabs
          value={active}
          onValueChange={(label) => {
            const tab = TABS.find((tb) => tb.label === label);
            if (tab) navigate(tab.path);
          }}
          className="relative mt-6 flex flex-row items-center space-x-1 overflow-auto md:space-x-0"
        >
          <TabsList aria-label={t('admin.tabsAriaLabel', 'Admin sections')}>
            {TABS.map((tab) => (
              <TabsTrigger key={tab.key} value={tab.label}>
                {t(`admin.tabs.${tab.key}`, tab.label)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Routes>
          <Route index element={<Overview />} />
          <Route path="users" element={<Users />} />
          <Route path="admins" element={<Admins />} />
          <Route path="usage" element={<Usage />} />
          <Route path="audit" element={<Audit />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </div>
    </div>
  );
}
