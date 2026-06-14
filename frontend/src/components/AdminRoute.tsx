import { useSelector } from 'react-redux';
import { Navigate } from 'react-router-dom';

import {
  selectIsAdmin,
  selectRolesResolved,
} from '../preferences/preferenceSlice';
import Spinner from './Spinner';

/**
 * Cosmetic route guard — NOT a security boundary. The server enforces admin
 * access via @admin_required on every /api/admin/* endpoint. This only avoids
 * rendering admin chrome to non-admins. Renders a spinner until roles are
 * resolved so a real admin is never bounced on first paint.
 */
export default function AdminRoute({
  children,
}: {
  children: React.ReactNode;
}) {
  const isAdmin = useSelector(selectIsAdmin);
  const rolesResolved = useSelector(selectRolesResolved);

  if (!rolesResolved) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}
