import {
  ChevronDown,
  Eye,
  Gauge,
  LogOut,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  UserX,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { ActionMenu, type MenuOption } from '../components/ui/dropdown-menu';
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
import SearchInput from '../components/SearchInput';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { LoadingState } from '../components/ui/loading-state';
import { Pagination } from '../components/ui/pagination';
import { EmptyState } from '../components/ui/empty-state';
import ConfirmationModal from '../modals/ConfirmationModal';
import { ActiveState } from '../models/misc';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import {
  LoadError,
  eventLabel,
  fmtDateShort,
  fmtNumber,
  fmtRelative,
} from './AdminUI';
import UserQuotaModal from './UserQuotaModal';
import UserUsageModal from './UserUsageModal';

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
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [adminIds, setAdminIds] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [menuUserId, setMenuUserId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any | null>(null);
  const [usageFor, setUsageFor] = useState<string | null>(null);
  const [quotaUserId, setQuotaUserId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{
    message: string;
    description: string;
    submitLabel: string;
    run: () => Promise<void>;
  } | null>(null);
  const [confirmState, setConfirmState] = useState<ActiveState>('INACTIVE');
  const [confirmError, setConfirmError] = useState<string>();

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
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
      setFailed(!usersRes.ok || usersJson.success === false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [token, page, query]);

  useEffect(() => {
    load();
  }, [load]);

  // A result the row can't show (a failure, Force logout) is a toast in the
  // app's shared ToastViewport (ActionToast), which auto-dismisses it. A
  // success the reloaded row shows (a badge) gets none.
  const setFeedback = (feedback: { ok: boolean; message: string }) =>
    dispatch(
      showActionToast({
        variant: feedback.ok ? 'success' : 'destructive',
        message: feedback.message,
      }),
    );

  // Runs an action and throws its failure message; `run` toasts it, a
  // confirm keeps it in the dialog. `successMsg` only for a result the
  // reloaded row doesn't show.
  const attempt = async (
    fn: () => Promise<Response>,
    userId: string,
    successMsg?: string,
  ) => {
    setBusy(userId);
    try {
      let res: Response;
      try {
        res = await fn();
      } catch {
        throw new Error(`Action failed for ${userId}`);
      }
      const json = await res.json().catch(() => ({}));
      if (!res.ok || json.success === false) {
        throw new Error(json.message || `Action failed for ${userId}`);
      }
      if (successMsg) setFeedback({ ok: true, message: successMsg });
      await load();
    } finally {
      setBusy(null);
    }
  };

  const run =
    (fn: () => Promise<Response>, userId: string, successMsg?: string) =>
    async () => {
      try {
        await attempt(fn, userId, successMsg);
      } catch (error) {
        setFeedback({ ok: false, message: (error as Error).message });
      }
    };

  // A confirmed action returns its promise to ConfirmationModal, which stays
  // pending while it runs and shows a failure in the dialog.
  const confirmed =
    (fn: () => Promise<Response>, userId: string) => async () => {
      setConfirmError(undefined);
      try {
        await attempt(fn, userId);
      } catch (error) {
        setConfirmError((error as Error).message);
        throw error;
      }
    };

  const askConfirm = (
    message: string,
    description: string,
    submitLabel: string,
    action: () => Promise<void>,
  ) => {
    setConfirmError(undefined);
    setConfirm({ message, description, submitLabel, run: action });
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
    const acts: Action[] = [
      {
        key: 'quota',
        label: 'Quota',
        icon: Gauge,
        perform: () => setQuotaUserId(userId),
      },
    ];
    if (isAdmin) {
      acts.push({
        key: 'revoke',
        label: 'Revoke admin',
        icon: ShieldOff,
        destructive: true,
        perform: () =>
          askConfirm(
            `Revoke admin from "${userId}"?`,
            'They lose access to the admin console. You can make them an admin again at any time.',
            'Revoke',
            confirmed(() => adminService.revokeAdmin(userId, token), userId),
          ),
      });
    } else {
      acts.push({
        key: 'grant',
        label: 'Make admin',
        icon: ShieldCheck,
        perform: run(() => adminService.grantAdmin(userId, token), userId),
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
            `Deactivate "${userId}"?`,
            'Their live sessions are revoked. You can activate them again at any time.',
            'Deactivate',
            confirmed(
              () => adminService.setUserActive(userId, false, token),
              userId,
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

  const applySearch = () => {
    setPage(1);
    setQuery(search.trim());
  };

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="w-full max-w-xs">
          <SearchInput
            label="Filter by user id"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') applySearch();
            }}
          />
        </div>
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
        <LoadingState fill="block" />
      ) : failed ? (
        <LoadError message="Failed to load users." onRetry={load} />
      ) : users.length === 0 ? (
        <EmptyState size="sm" illustration="none" title="No users found." />
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
                      onClick={() => openDetail(u.user_id)}
                    >
                      <TableCell className="max-w-[280px]">
                        <span
                          className="block truncate font-mono text-xs"
                          title={u.user_id}
                        >
                          {u.user_id}
                        </span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {isAdmin ? (
                            <Badge variant="default">Admin</Badge>
                          ) : null}
                          {!u.active ? (
                            <Badge variant="destructive">Inactive</Badge>
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
                          <ActionMenu
                            open={menuUserId === u.user_id}
                            onOpenChange={(open) =>
                              setMenuUserId(open ? u.user_id : null)
                            }
                            disabled={disabled}
                            triggerLabel="User actions"
                            options={[
                              {
                                label: 'View details',
                                icon: Eye,
                                onClick: () => openDetail(u.user_id),
                              },
                              ...buildActions(u.user_id, isAdmin, u.active).map(
                                (act): MenuOption => ({
                                  label: act.label,
                                  icon: act.icon,
                                  variant: act.destructive
                                    ? 'destructive'
                                    : 'default',
                                  onClick: act.perform,
                                }),
                              ),
                            ]}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <Pagination
            page={page}
            pageSize={PAGE_SIZE}
            total={total}
            onPageChange={setPage}
            rangeLabel={({ from, to }) =>
              `${fmtNumber(from)}–${fmtNumber(to)} of ${fmtNumber(total)} users`
            }
          />
        </>
      )}

      {confirm ? (
        <ConfirmationModal
          message={confirm.message}
          description={confirm.description}
          modalState={confirmState}
          setModalState={setConfirmState}
          submitLabel={confirm.submitLabel}
          variant="destructive"
          handleSubmit={confirm.run}
          error={confirmError}
        />
      ) : null}

      <UserUsageModal userId={usageFor} onClose={() => setUsageFor(null)} />
      <UserQuotaModal
        userId={quotaUserId}
        onClose={() => setQuotaUserId(null)}
      />

      <Modal
        open={detail !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
        title={detail?.user?.user_id ?? 'User'}
        size="lg"
        footer={
          detail ? (
            <ActionMenu
              trigger={
                <Button type="button" variant="outline" size="lg" shape="pill">
                  Actions
                  <ChevronDown />
                </Button>
              }
              menuWidth="sm"
              options={buildActions(
                detail.user.user_id,
                (detail.roles ?? []).includes('admin'),
                detail.user?.active ?? true,
              ).map((act): MenuOption => ({
                label: act.label,
                icon: act.icon,
                variant: act.destructive ? 'destructive' : 'default',
                onClick: () => {
                  // Close the detail dialog before any confirm dialog opens
                  // (avoids stacked modals); the list + toast reflect the result.
                  setDetail(null);
                  act.perform();
                },
              }))}
            />
          ) : undefined
        }
      >
        {detail ? (
          <div className="flex flex-col gap-4 text-sm">
            <div>
              <p className="text-muted-foreground mb-1 text-xs">
                Roles & status
              </p>
              <div className="flex flex-wrap gap-2">
                {(detail.roles ?? []).map((r: string) => (
                  <Badge
                    key={r}
                    variant={r === 'admin' ? 'default' : 'neutral'}
                  >
                    {r}
                  </Badge>
                ))}
                {detail.user?.active ? (
                  <Badge variant="success">Active</Badge>
                ) : (
                  <Badge variant="destructive">Inactive</Badge>
                )}
              </div>
            </div>
            <DescriptionList layout="justified" size="sm" columns={2}>
              <DescriptionItem label="Agents">
                {fmtNumber(detail.counts?.agents)}
              </DescriptionItem>
              <DescriptionItem label="Sources">
                {fmtNumber(detail.counts?.sources)}
              </DescriptionItem>
              <DescriptionItem label="Conversations">
                {fmtNumber(detail.counts?.conversations)}
              </DescriptionItem>
              <DescriptionItem label="Tokens (30d)">
                {fmtNumber(detail.counts?.tokens_30d)}
              </DescriptionItem>
            </DescriptionList>
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              onClick={() => {
                // Close the detail dialog before the usage dialog opens, so
                // the two never stack.
                const userId = detail.user.user_id;
                setDetail(null);
                setUsageFor(userId);
              }}
            >
              View spend breakdown
            </Button>
            <div>
              <p className="text-muted-foreground mb-1 text-xs">
                Recent auth events
              </p>
              <div className="flex max-h-64 flex-col gap-1 overflow-auto">
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
