import {
  Eye,
  LogOut,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  UserX,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import ThreeDots from '../assets/three-dots.svg';
import { Button } from '../components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../components/ui/dropdown-menu';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import {
  Loading,
  Pill,
  eventLabel,
  fmtDateShort,
  fmtNumber,
  fmtRelative,
} from './AdminUI';

type AdminUser = {
  user_id: string;
  active: boolean;
  created_at?: string;
  last_seen?: string | null;
};

type Action = {
  key: string;
  label: string;
  icon: typeof Eye;
  destructive?: boolean;
  perform: () => void;
};

const PAGE_SIZE = 25;

export default function Users() {
  const token = useSelector(selectToken);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [adminIds, setAdminIds] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [menuUserId, setMenuUserId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [feedback, setFeedback] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [confirm, setConfirm] = useState<{
    message: string;
    submitLabel: string;
    run: () => void;
  } | null>(null);
  const [confirmState, setConfirmState] = useState<ActiveState>('INACTIVE');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [usersRes, adminsRes] = await Promise.all([
        adminService.getUsers(
          { page, page_size: PAGE_SIZE, user_id: query || undefined },
          token,
        ),
        adminService.getAdmins(token),
      ]);
      const usersJson = await usersRes.json().catch(() => ({}));
      const adminsJson = await adminsRes.json().catch(() => ({}));
      setUsers(usersJson.users ?? []);
      setTotal(usersJson.total ?? 0);
      setAdminIds(
        new Set((adminsJson.admins ?? []).map((a: any) => a.user_id)),
      );
    } finally {
      setLoading(false);
    }
  }, [token, page, query]);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-dismiss the inline feedback banner.
  useEffect(() => {
    if (!feedback) return;
    const id = setTimeout(() => setFeedback(null), 4500);
    return () => clearTimeout(id);
  }, [feedback]);

  const run =
    (fn: () => Promise<Response>, userId: string, successMsg: string) =>
    async () => {
      setBusy(userId);
      try {
        const res = await fn();
        const json = await res.json().catch(() => ({}));
        if (res.ok && json.success !== false) {
          setFeedback({ ok: true, message: successMsg });
          await load();
        } else {
          setFeedback({
            ok: false,
            message: json.message || `Action failed for ${userId}`,
          });
        }
      } catch {
        setFeedback({ ok: false, message: `Action failed for ${userId}` });
      } finally {
        setBusy(null);
      }
    };

  const askConfirm = (
    message: string,
    submitLabel: string,
    action: () => void,
  ) => {
    setConfirm({ message, submitLabel, run: action });
    setConfirmState('ACTIVE');
  };

  const openDetail = async (userId: string) => {
    const res = await adminService.getUser(userId, token);
    const json = await res.json().catch(() => ({}));
    if (json.success) setDetail(json);
  };

  const buildActions = (
    userId: string,
    isAdmin: boolean,
    active: boolean,
  ): Action[] => {
    const acts: Action[] = [];
    if (isAdmin) {
      acts.push({
        key: 'revoke',
        label: 'Revoke admin',
        icon: ShieldOff,
        destructive: true,
        perform: () =>
          askConfirm(
            `Revoke admin from ${userId}?`,
            'Revoke',
            run(
              () => adminService.revokeAdmin(userId, token),
              userId,
              `Removed admin from ${userId}`,
            ),
          ),
      });
    } else {
      acts.push({
        key: 'grant',
        label: 'Make admin',
        icon: ShieldCheck,
        perform: run(
          () => adminService.grantAdmin(userId, token),
          userId,
          `${userId} is now an admin`,
        ),
      });
    }
    if (active) {
      acts.push({
        key: 'deactivate',
        label: 'Deactivate',
        icon: UserX,
        destructive: true,
        perform: () =>
          askConfirm(
            `Deactivate ${userId}? This revokes their live sessions.`,
            'Deactivate',
            run(
              () => adminService.setUserActive(userId, false, token),
              userId,
              `${userId} deactivated`,
            ),
          ),
      });
    } else {
      acts.push({
        key: 'activate',
        label: 'Activate',
        icon: UserCheck,
        perform: run(
          () => adminService.setUserActive(userId, true, token),
          userId,
          `${userId} reactivated`,
        ),
      });
    }
    acts.push({
      key: 'logout',
      label: 'Force logout',
      icon: LogOut,
      perform: run(
        () => adminService.revokeSessions(userId, token),
        userId,
        `Sessions revoked for ${userId}`,
      ),
    });
    return acts;
  };

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const applySearch = () => {
    setPage(1);
    setQuery(search.trim());
  };

  return (
    <div className="mt-6">
      {feedback ? (
        <div
          className={`mb-4 rounded-xl border px-4 py-2 text-sm ${
            feedback.ok
              ? 'border-green-300 bg-green-50 text-green-700 dark:border-green-900/50 dark:bg-green-950/30 dark:text-green-300'
              : 'border-red-300 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300'
          }`}
        >
          {feedback.message}
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          placeholder="Filter by user id"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') applySearch();
          }}
          className="max-w-xs"
        />
        <Button variant="outline" size="sm" onClick={applySearch}>
          Search
        </Button>
        {query ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setSearch('');
              setQuery('');
              setPage(1);
            }}
          >
            Clear
          </Button>
        ) : null}
      </div>

      {loading ? (
        <Loading />
      ) : users.length === 0 ? (
        <p className="text-muted-foreground mt-8 text-sm">No users found.</p>
      ) : (
        <>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>User</TableHeader>
                  <TableHeader>Tags</TableHeader>
                  <TableHeader>Last seen</TableHeader>
                  <TableHeader>Created</TableHeader>
                  <TableHeader className="text-right">Actions</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((u) => {
                  const isAdmin = adminIds.has(u.user_id);
                  const disabled = busy === u.user_id;
                  return (
                    <TableRow
                      key={u.user_id}
                      className="hover:bg-muted/40 cursor-pointer"
                      onClick={() => openDetail(u.user_id)}
                    >
                      <TableCell className="max-w-[280px]">
                        <span
                          className="block truncate font-mono text-[13px]"
                          title={u.user_id}
                        >
                          {u.user_id}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {isAdmin ? <Pill tone="brand">Admin</Pill> : null}
                          {!u.active ? (
                            <Pill tone="danger">Inactive</Pill>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        <span title={u.last_seen ?? 'never'}>
                          {fmtRelative(u.last_seen)}
                        </span>
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        <span title={u.created_at ?? ''}>
                          {fmtDateShort(u.created_at)}
                        </span>
                      </TableCell>
                      <TableCell className="text-right">
                        <div
                          className="flex items-center justify-end"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <DropdownMenu
                            open={menuUserId === u.user_id}
                            onOpenChange={(open) =>
                              setMenuUserId(open ? u.user_id : null)
                            }
                          >
                            <DropdownMenuTrigger asChild>
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                disabled={disabled}
                                className="text-muted-foreground hover:text-foreground h-[35px] w-7"
                                aria-label="User actions"
                              >
                                <img
                                  src={ThreeDots}
                                  alt="User actions"
                                  className="filter dark:invert"
                                />
                              </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                              align="end"
                              className="min-w-[176px]"
                            >
                              <DropdownMenuItem
                                onSelect={() => openDetail(u.user_id)}
                              >
                                <Eye size={16} />
                                <span>View details</span>
                              </DropdownMenuItem>
                              {buildActions(u.user_id, isAdmin, u.active).map(
                                (act) => (
                                  <DropdownMenuItem
                                    key={act.key}
                                    variant={
                                      act.destructive
                                        ? 'destructive'
                                        : 'default'
                                    }
                                    onSelect={act.perform}
                                  >
                                    <act.icon size={16} />
                                    <span>{act.label}</span>
                                  </DropdownMenuItem>
                                ),
                              )}
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              {fmtNumber(total)} users · page {page} of {totalPages}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}

      {confirm ? (
        <ConfirmationModal
          message={confirm.message}
          modalState={confirmState}
          setModalState={setConfirmState}
          submitLabel={confirm.submitLabel}
          variant="danger"
          handleSubmit={() => {
            confirm.run();
            setConfirm(null);
          }}
        />
      ) : null}

      <Modal
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.user?.user_id ?? 'User'}
        size="lg"
        footer={
          detail ? (
            <div className="flex flex-wrap justify-end gap-2">
              {buildActions(
                detail.user.user_id,
                (detail.roles ?? []).includes('admin'),
                detail.user?.active ?? true,
              ).map((act) => (
                <Button
                  key={act.key}
                  type="button"
                  variant={act.destructive ? 'destructive-outline' : 'outline'}
                  size="sm"
                  onClick={() => {
                    // Close the detail dialog before any confirm dialog opens
                    // (avoids stacked modals); the list + banner reflect the result.
                    setDetail(null);
                    act.perform();
                  }}
                >
                  <act.icon size={16} />
                  {act.label}
                </Button>
              ))}
            </div>
          ) : undefined
        }
      >
        {detail ? (
          <div className="space-y-4 text-sm">
            <div>
              <p className="text-muted-foreground mb-1 text-xs">
                Roles & status
              </p>
              <div className="flex flex-wrap gap-2">
                {(detail.roles ?? []).map((r: string) => (
                  <Pill key={r} tone={r === 'admin' ? 'brand' : 'muted'}>
                    {r}
                  </Pill>
                ))}
                {detail.user?.active ? (
                  <Pill tone="success">Active</Pill>
                ) : (
                  <Pill tone="danger">Inactive</Pill>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Agents</span>
                <span className="tabular-nums">
                  {fmtNumber(detail.counts?.agents)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Sources</span>
                <span className="tabular-nums">
                  {fmtNumber(detail.counts?.sources)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Conversations</span>
                <span className="tabular-nums">
                  {fmtNumber(detail.counts?.conversations)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Tokens (30d)</span>
                <span className="tabular-nums">
                  {fmtNumber(detail.counts?.tokens_30d)}
                </span>
              </div>
            </div>
            <div>
              <p className="text-muted-foreground mb-1 text-xs">
                Recent auth events
              </p>
              <div className="max-h-64 space-y-1 overflow-auto">
                {(detail.recent_events ?? []).length === 0 ? (
                  <p className="text-muted-foreground">None</p>
                ) : (
                  (detail.recent_events ?? []).map((ev: any) => (
                    <div
                      key={ev.id}
                      className="flex items-center justify-between gap-2"
                    >
                      <span>{eventLabel(ev.event)}</span>
                      <span className="text-muted-foreground whitespace-nowrap">
                        {fmtRelative(ev.created_at)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
