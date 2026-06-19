import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import SkeletonLoader from '../components/SkeletonLoader';
import { Button } from '../components/ui/button';
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
import { formatDate } from '../utils/dateTimeUtils';
import { Loading, LoadError, StatCard, fmtNumber } from './AdminUI';
import UsageChart, { usageColors } from './UsageChart';

type Bucket = {
  bucket: string;
  prompt_tokens: number;
  generated_tokens: number;
};
type TopUser = { user_id: string; tokens: number };

const RANGES = [7, 30, 90];

export default function Usage() {
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminService.getUsage({ days, bucket: 'day' }, token);
      setData(await res.json().catch(() => ({})));
    } finally {
      setLoading(false);
    }
  }, [token, days]);

  useEffect(() => {
    load();
  }, [load]);

  const series: Bucket[] = data?.series ?? [];
  const topUsers: TopUser[] = data?.top_users ?? [];
  const promptTotal = series.reduce((sum, b) => sum + b.prompt_tokens, 0);
  const generatedTotal = series.reduce((sum, b) => sum + b.generated_tokens, 0);

  const chartData = useMemo(() => {
    const colors = usageColors();
    return {
      labels: series.map((b) => formatDate(b.bucket)),
      datasets: [
        {
          label: 'Prompt',
          data: series.map((b) => b.prompt_tokens),
          backgroundColor: colors.prompt,
        },
        {
          label: 'Generated',
          data: series.map((b) => b.generated_tokens),
          backgroundColor: colors.generated,
        },
      ],
    };
    // isDarkTheme re-resolves the canvas colors when the theme toggles.
  }, [series, isDarkTheme]);

  if (data === null && loading) return <Loading />;
  if (data && !data.success)
    return <LoadError message="Failed to load usage." />;

  return (
    <div className="mt-6">
      <div className="mb-4 flex items-center gap-1">
        {RANGES.map((r) => (
          <Button
            key={r}
            variant={r === days ? 'default' : 'outline'}
            size="sm"
            className="rounded-3xl"
            onClick={() => setDays(r)}
          >
            {r}d
          </Button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard
          label={`Total tokens (${days}d)`}
          value={fmtNumber(data?.total_tokens)}
        />
        <StatCard label="Prompt tokens" value={fmtNumber(promptTotal)} />
        <StatCard label="Generated tokens" value={fmtNumber(generatedTotal)} />
        <StatCard label="Days with usage" value={fmtNumber(series.length)} />
      </div>

      <div className="border-border dark:border-border mt-4 h-[345px] w-full overflow-hidden rounded-2xl border px-6 py-5">
        <div className="flex flex-row items-center justify-between gap-3">
          <p className="text-foreground dark:text-foreground font-bold">
            Token usage
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
            <UsageChart data={chartData} legendID="admin-usage-legend" />
          )}
        </div>
      </div>

      <div className="border-border dark:border-border mt-4 w-full overflow-hidden rounded-2xl border px-6 py-5">
        <p className="text-foreground dark:text-foreground mb-3 font-bold">
          Top users by tokens
        </p>
        {topUsers.length === 0 ? (
          <p className="text-muted-foreground text-sm">No usage.</p>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>User</TableHeader>
                  <TableHeader className="text-right">Tokens</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {topUsers.map((u) => (
                  <TableRow key={u.user_id}>
                    <TableCell className="font-mono text-[13px] break-all">
                      {u.user_id}
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap tabular-nums">
                      {fmtNumber(u.tokens)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </div>
    </div>
  );
}
