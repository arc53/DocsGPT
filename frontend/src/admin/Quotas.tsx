import { TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import adminService, { type QuotaScope } from '../api/services/adminService';
import teamsService from '../api/services/teamsService';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
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
import { LoadingState } from '@/components/ui/loading-state';
import { LoadError, fmtDate, fmtNumber, fmtRelative } from './AdminUI';
import QuotaEditor from './QuotaEditor';
import { describeBudget, type QuotaPolicy } from './quotaUtils';

type TeamPolicy = QuotaPolicy & {
  team_name?: string | null;
  team_slug?: string | null;
  member_count?: number | null;
};

type Editing = {
  scope: QuotaScope;
  subjectId: string | null;
  title: string;
  policy: QuotaPolicy | null;
};

const HINTS: Record<QuotaScope, string> = {
  instance:
    'Applies to every user that no team allowance or user override covers.',
  team: 'Each member gets this allowance; it is not a shared pool. A member of several teams gets the most generous one.',
  user: 'Overrides team allowances and the instance default for this user.',
};

// React escapes on render; i18next's own escaping would mangle model ids
// such as `org/model` into `org&#x2F;model`.
const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

function PolicyCells({ policy }: { policy: QuotaPolicy }) {
  return (
    <>
      <TableCell className="tabular-nums">
        {describeBudget(policy.token_limit, policy.token_unlimited, 'tokens')}
      </TableCell>
      <TableCell className="tabular-nums">
        {describeBudget(policy.cost_limit_usd, policy.cost_unlimited, 'cost')}
      </TableCell>
      <TableCell className="text-muted-foreground max-w-56 truncate">
        {policy.note || '—'}
      </TableCell>
      <TableCell className="text-muted-foreground whitespace-nowrap">
        {fmtRelative(policy.updated_at)}
      </TableCell>
    </>
  );
}

export default function Quotas() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [data, setData] = useState<any | null>(null);
  const [teams, setTeams] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [teamPick, setTeamPick] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [quotasRes, teamsJson] = await Promise.all([
        adminService.getQuotas(token),
        teamsService.listAll(token).catch(() => ({})),
      ]);
      setData(await quotasRes.json().catch(() => ({ success: false })));
      setTeams(teamsJson?.teams ?? []);
    } catch {
      setData({ success: false });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  // The editor covers the ``all`` bucket; other buckets are listed read-only.
  const isAll = (p: QuotaPolicy) => p.bucket === 'all';
  const instancePolicy: QuotaPolicy | null =
    (data?.instance ?? []).find(isAll) ?? null;
  const teamPolicies: TeamPolicy[] = data?.teams ?? [];
  const userPolicies: QuotaPolicy[] = data?.users ?? [];
  const teamsWithoutPolicy = useMemo(() => {
    const covered = new Set(
      teamPolicies.filter(isAll).map((p) => String(p.subject_id)),
    );
    return teams.filter((team) => !covered.has(String(team.id)));
  }, [teams, teamPolicies]);

  if (data === null && loading) return <LoadingState fill="block" />;
  if (!data?.success)
    return <LoadError message="Failed to load quotas." onRetry={load} />;

  const bucketPill = (policy: QuotaPolicy) => (
    <>
      {isAll(policy) ? null : (
        <Badge variant="neutral">{policy.bucket} traffic</Badge>
      )}
      {policy.enabled ? null : <Badge variant="neutral">Disabled</Badge>}
    </>
  );

  return (
    <div className="flex flex-col gap-8">
      <p className="text-muted-foreground text-sm">
        Usage is counted per user over each calendar {data.period} (UTC). The
        current window resets {fmtDate(data.resets_at)}. A request is refused
        once a budget is used up; the request that crosses it still completes.
      </p>

      {(data.unpriced_models ?? []).length > 0 ? (
        <Alert variant="warning" role="note">
          <TriangleAlert className="size-4" aria-hidden="true" />
          <AlertTitle>{t('admin.quotas.unpriced.title')}</AlertTitle>
          <AlertDescription>
            <p>
              {t('admin.quotas.unpriced.body', {
                period: data.period,
                models: (data.unpriced_models as any[])
                  .map((m) =>
                    t('admin.quotas.unpriced.model', {
                      model: m.model_id,
                      tokens: fmtNumber(m.tokens),
                      ...NO_ESCAPE,
                    }),
                  )
                  .join(', '),
                ...NO_ESCAPE,
              })}
            </p>
          </AlertDescription>
        </Alert>
      ) : null}

      <section>
        <SectionHeader
          title="Instance default"
          actions={
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setEditing({
                  scope: 'instance',
                  subjectId: null,
                  title: 'Instance default',
                  policy: instancePolicy,
                })
              }
            >
              {instancePolicy ? 'Edit' : 'Set default'}
            </Button>
          }
        />
        <p className="text-muted-foreground mt-1 text-sm">
          {instancePolicy
            ? `${instancePolicy.enabled ? '' : 'Disabled · '}Tokens: ${describeBudget(instancePolicy.token_limit, instancePolicy.token_unlimited, 'tokens')} · Cost: ${describeBudget(instancePolicy.cost_limit_usd, instancePolicy.cost_unlimited, 'cost')}`
            : 'No default: users without a team allowance or override are unlimited.'}
        </p>
      </section>

      <section>
        <SectionHeader
          title="Team allowances"
          actions={
            teamsWithoutPolicy.length > 0 ? (
              <>
                <Select value={teamPick} onValueChange={setTeamPick}>
                  <SelectTrigger className="w-52" aria-label="Team">
                    <SelectValue placeholder="Choose a team" />
                  </SelectTrigger>
                  <SelectContent>
                    {teamsWithoutPolicy.map((team) => (
                      <SelectItem key={team.id} value={String(team.id)}>
                        {team.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!teamPick}
                  onClick={() => {
                    const team = teams.find((tm) => String(tm.id) === teamPick);
                    setEditing({
                      scope: 'team',
                      subjectId: teamPick,
                      title: team?.name ?? 'Team',
                      policy: null,
                    });
                  }}
                >
                  Add allowance
                </Button>
              </>
            ) : null
          }
        />
        {teamPolicies.length === 0 ? (
          <p className="text-muted-foreground mt-1 text-sm">
            No team has an allowance.
          </p>
        ) : (
          <TableContainer className="mt-3">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>Team</TableHeader>
                  <TableHeader>Members</TableHeader>
                  <TableHeader>Tokens</TableHeader>
                  <TableHeader>Cost</TableHeader>
                  <TableHeader>Note</TableHeader>
                  <TableHeader>Updated</TableHeader>
                  <TableHeader className="text-right">Actions</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {teamPolicies.map((policy) => (
                  <TableRow key={`${policy.subject_id}:${policy.bucket}`}>
                    <TableCell>
                      <span className="mr-2">
                        {policy.team_name ?? policy.subject_id}
                      </span>
                      {bucketPill(policy)}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {fmtNumber(policy.member_count)}
                    </TableCell>
                    <PolicyCells policy={policy} />
                    <TableCell className="text-right">
                      {isAll(policy) ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setEditing({
                              scope: 'team',
                              subjectId: policy.subject_id,
                              title: policy.team_name ?? 'Team',
                              policy,
                            })
                          }
                        >
                          Edit
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </section>

      <section>
        <SectionHeader title="User overrides" />
        {userPolicies.length === 0 ? (
          <p className="text-muted-foreground mt-1 text-sm">
            No user has an override. Add one from a user&apos;s menu on the
            Users tab.
          </p>
        ) : (
          <TableContainer className="mt-3">
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>User</TableHeader>
                  <TableHeader>Tokens</TableHeader>
                  <TableHeader>Cost</TableHeader>
                  <TableHeader>Note</TableHeader>
                  <TableHeader>Updated</TableHeader>
                  <TableHeader className="text-right">Actions</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {userPolicies.map((policy) => (
                  <TableRow key={`${policy.subject_id}:${policy.bucket}`}>
                    <TableCell>
                      <span className="mr-2 break-all">
                        {policy.subject_id}
                      </span>
                      {bucketPill(policy)}
                    </TableCell>
                    <PolicyCells policy={policy} />
                    <TableCell className="text-right">
                      {isAll(policy) ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setEditing({
                              scope: 'user',
                              subjectId: policy.subject_id,
                              title: policy.subject_id ?? 'User',
                              policy,
                            })
                          }
                        >
                          Edit
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </section>

      <Modal
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) setEditing(null);
        }}
        title={editing ? `Quota · ${editing.title}` : 'Quota'}
      >
        {editing ? (
          <QuotaEditor
            scope={editing.scope}
            subjectId={editing.subjectId}
            policy={editing.policy}
            inheritHint={HINTS[editing.scope]}
            onSaved={() => {
              setEditing(null);
              setTeamPick('');
              load();
            }}
          />
        ) : null}
      </Modal>
    </div>
  );
}
