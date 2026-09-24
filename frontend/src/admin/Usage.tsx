import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
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
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import {
  Loading,
  LoadError,
  StatCard,
  fmtMs,
  fmtNumber,
  fmtUsd,
} from './AdminUI';
import UsageChart from './UsageChart';
import {
  GROUP_OPTIONS,
  buildUsageChart,
  cacheHitRate as computeCacheHitRate,
  type GroupBy,
  type Metric,
  type UsageBucket,
} from './usageChartData';
import UserUsageModal from './UserUsageModal';

type TopUser = { user_id: string; tokens: number; cost: number };
type Latency = {
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
  ttft_samples: number;
  ttft_p50_ms: number | null;
};

const RANGES = [7, 30, 90];

export default function Usage() {
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [days, setDays] = useState(30);
  const [groupBy, setGroupBy] = useState<GroupBy>('none');
  const [metric, setMetric] = useState<Metric>('tokens');
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [drilldown, setDrilldown] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminService.getUsage(
        { days, bucket: 'day', group_by: groupBy },
        token,
      );
      setData(await res.json().catch(() => ({})));
    } finally {
      setLoading(false);
    }
  }, [token, days, groupBy]);

  useEffect(() => {
    load();
  }, [load]);

  const series: UsageBucket[] = data?.series ?? [];
  const topUsers: TopUser[] = data?.top_users ?? [];
  const latency: Latency | undefined = data?.latency;

  const chartData = useMemo(
    () => buildUsageChart(series, groupBy, metric),
    // isDarkTheme re-resolves the canvas colors when the theme toggles.
    [series, groupBy, metric, isDarkTheme],
  );

  const cacheHitRate = useMemo(() => computeCacheHitRate(series), [series]);

  if (data === null && loading) return <Loading />;
  if (data && !data.success)
    return <LoadError message="Failed to load usage." />;

  return (
    <div className="mt-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          {RANGES.map((range) => (
            <Button
              key={range}
              variant={range === days ? 'default' : 'outline'}
              size="sm"
              shape="pill"
              onClick={() => setDays(range)}
            >
              {range}d
            </Button>
          ))}
        </div>
        <Select
          value={groupBy}
          onValueChange={(value) => setGroupBy(value as GroupBy)}
        >
          <SelectTrigger className="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {GROUP_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="flex items-center gap-1">
          <Button
            variant={metric === 'tokens' ? 'default' : 'outline'}
            size="sm"
            shape="pill"
            onClick={() => setMetric('tokens')}
          >
            Tokens
          </Button>
          <Button
            variant={metric === 'cost' ? 'default' : 'outline'}
            size="sm"
            shape="pill"
            onClick={() => setMetric('cost')}
          >
            Cost
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label={`Spend (${days}d)`}
          value={fmtUsd(data?.total_cost)}
          sub="Unpriced and BYO models record $0"
        />
        <StatCard
          label={`Tokens (${days}d)`}
          value={fmtNumber(data?.total_tokens)}
        />
        <StatCard
          label="Latency p50 / p95"
          value={`${fmtMs(latency?.p50_ms)} / ${fmtMs(latency?.p95_ms)}`}
          sub={
            latency?.ttft_p50_ms !== null && latency?.ttft_p50_ms !== undefined
              ? `First token ${fmtMs(latency.ttft_p50_ms)} (p50)`
              : 'No streamed calls measured'
          }
        />
        <StatCard
          label="Prompt cache hits"
          value={cacheHitRate === null ? '—' : `${cacheHitRate.toFixed(1)}%`}
          sub={
            cacheHitRate === null
              ? 'Provider reported no cache data'
              : 'Of prompt tokens on calls that reported'
          }
        />
      </div>

      <div className="border-border dark:border-border mt-4 h-[345px] w-full overflow-hidden rounded-2xl border px-6 py-5">
        <div className="flex flex-row items-center justify-between gap-3">
          <p className="text-foreground dark:text-foreground font-bold">
            {metric === 'cost' ? 'Spend' : 'Token usage'}
          </p>
          <div
            id="admin-usage-legend"
            className="flex flex-row items-center justify-end"
          ></div>
        </div>
        <div className="relative mt-px h-[260px] w-full">
          {loading ? (
            <SkeletonLoader count={1} component={'analysis'} />
          ) : series.length === 0 ? (
            <p className="text-muted-foreground mt-8 text-sm">
              No usage in this period.
            </p>
          ) : (
            <UsageChart
              data={chartData}
              legendID="admin-usage-legend"
              currency={metric === 'cost'}
            />
          )}
        </div>
      </div>

      <div className="border-border dark:border-border mt-4 w-full overflow-hidden rounded-2xl border px-6 py-5">
        <p className="text-foreground dark:text-foreground mb-3 font-bold">
          Top users
        </p>
        {topUsers.length === 0 ? (
          <p className="text-muted-foreground text-sm">No usage.</p>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>User</TableHeader>
                  <TableHeader align="right">Tokens</TableHeader>
                  <TableHeader align="right">Cost</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {topUsers.map((user) => (
                  <TableRow key={user.user_id}>
                    <TableCell className="font-mono text-xs break-all">
                      <button
                        type="button"
                        className="hover:text-foreground focus-visible:ring-ring cursor-pointer rounded text-left underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                        onClick={() => setDrilldown(user.user_id)}
                      >
                        {user.user_id}
                      </button>
                    </TableCell>
                    <TableCell
                      align="right"
                      className="whitespace-nowrap tabular-nums"
                    >
                      {fmtNumber(user.tokens)}
                    </TableCell>
                    <TableCell
                      align="right"
                      className="whitespace-nowrap tabular-nums"
                    >
                      {fmtUsd(user.cost)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </div>

      <UserUsageModal userId={drilldown} onClose={() => setDrilldown(null)} />
    </div>
  );
}
