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
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { selectToken } from '../preferences/preferenceSlice';
import { LoadingState } from '@/components/ui/loading-state';
import StatCard from '@/components/StatCard';
import { Card } from '@/components/ui/card';
import { SectionHeader } from '@/components/ui/section-header';
import { LoadError, fmtMs, fmtNumber, fmtUsd } from './AdminUI';
import { useChartPalette } from '../utils/chartUtils';
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
  // Re-read on every theme change; Chart.js can't read CSS variables.
  const palette = useChartPalette();
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
    } catch {
      setData({});
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
    () => buildUsageChart(series, groupBy, metric, palette),
    [series, groupBy, metric, palette],
  );

  const cacheHitRate = useMemo(() => computeCacheHitRate(series), [series]);

  if (data === null && loading) return <LoadingState fill="block" />;
  if (data && !data.success)
    return <LoadError message="Failed to load usage." onRetry={load} />;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <ToggleGroup
          type="single"
          size="sm"
          value={String(days)}
          onValueChange={(value) => value && setDays(Number(value))}
          aria-label="Range"
        >
          {RANGES.map((range) => (
            <ToggleGroupItem key={range} value={String(range)}>
              {range}d
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
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
        <ToggleGroup
          type="single"
          size="sm"
          value={metric}
          onValueChange={(value) => value && setMetric(value as Metric)}
          aria-label="Metric"
        >
          <ToggleGroupItem value="tokens">Tokens</ToggleGroupItem>
          <ToggleGroupItem value="cost">Cost</ToggleGroupItem>
        </ToggleGroup>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
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

      <Card
        variant="subtle"
        padding="lg"
        className="mt-4 h-[345px] w-full overflow-hidden"
      >
        <div className="flex flex-row items-center justify-between gap-3">
          <SectionHeader
            as="h3"
            size="xs"
            title={metric === 'cost' ? 'Spend' : 'Token usage'}
          />
          <div
            id="admin-usage-legend"
            className="flex flex-row items-center justify-end"
          ></div>
        </div>
        <div className="relative h-[260px] w-full">
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
              gridColor={palette.border}
              tickColor={palette.mutedForeground}
            />
          )}
        </div>
      </Card>

      <Card
        variant="subtle"
        padding="lg"
        className="mt-4 w-full overflow-hidden"
      >
        <SectionHeader as="h3" size="xs" title="Top users" />
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
                      <Button
                        type="button"
                        variant="link"
                        size="inline"
                        // eslint-disable-next-line shadcn/no-restyle -- the id keeps the cell's 12px mono type and wraps
                        className="text-left font-mono text-xs font-normal whitespace-normal"
                        onClick={() => setDrilldown(user.user_id)}
                      >
                        {user.user_id}
                      </Button>
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
      </Card>

      <UserUsageModal userId={drilldown} onClose={() => setDrilldown(null)} />
    </div>
  );
}
