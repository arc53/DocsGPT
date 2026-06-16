import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { selectToken } from '../preferences/preferenceSlice';
import { Loading, Pill, fmtDate } from './AdminUI';

type Admin = { user_id: string; granted_at?: string; sources?: string[] };

export default function Admins() {
  const token = useSelector(selectToken);
  const [admins, setAdmins] = useState<Admin[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    adminService
      .getAdmins(token)
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled) {
          setAdmins(json.admins ?? []);
          setLoading(false);
        }
      })
      .catch(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [token]);

  if (loading) return <Loading />;

  return (
    <div className="mt-6">
      <p className="text-muted-foreground mb-4 text-sm">
        Admin access is the deployment super-admin role. Grant or revoke it from
        the Users tab; OIDC-group-derived grants reconcile automatically at
        login.
      </p>
      {admins.length === 0 ? (
        <p className="text-muted-foreground text-sm">No admins.</p>
      ) : (
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>User</TableHeader>
                <TableHeader>Sources</TableHeader>
                <TableHeader>Granted</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {admins.map((a) => (
                <TableRow key={a.user_id}>
                  <TableCell className="font-medium break-all">
                    {a.user_id}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {(a.sources ?? []).map((s) => (
                        <Pill key={s} tone="muted">
                          {s}
                        </Pill>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground whitespace-nowrap">
                    {fmtDate(a.granted_at)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </div>
  );
}
