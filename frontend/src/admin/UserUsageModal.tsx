import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
import { Button } from '../components/ui/button';
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
import { useDarkTheme } from '../hooks';
import { selectToken } from '../preferences/preferenceSlice';
import { formatDate } from '../utils/dateTimeUtils';
import { Loading, LoadError, StatCard, fmtNumber, fmtUsd } from './AdminUI';
import UsageChart, { usageColors } from './UsageChart';

type Bucket = {
  bucket: string;
  prompt_tokens: number;
  generated_tokens: number;
  cost: number;
};
type Split = { key: string; tokens: number; cost: number };

const RANGES = [7, 30, 90];

/** Label for a token_usage.source value — what the spend was for. */
const FLOW_LABELS: Record<string, string> = {
  agent_stream: 'Chat',
  schedule: 'Scheduled run',
  webhook: 'Webhook',
  workflow: 'Workflow',
  title: 'Title generation',
  compression: 'History compression',
  rag_condense: 'Question condensing',
  fallback: 'Provider fallback',
};

function SplitTable({
  title,
  rows,
  labels,
}: {
  title: string;
  rows: Split[];
  /** Only the flow table maps keys; a model named `fallback` is a model. */
  labels?: Record<string, string>;
}) {
  return (
    <div>
      <p className="text-muted-foreground mb-2 text-sm font-medium">{title}</p>
      {rows.length === 0 ? (
        <p className="text-muted-foreground text-sm">No usage.</p>
      ) : (
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader>{title}</TableHeader>
                <TableHeader align="right">Tokens</TableHeader>
                <TableHeader align="right">Cost</TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.key}>
                  <TableCell className="text-[13px] break-all">
                    {labels?.[row.key] ?? row.key}
                  </TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {fmtNumber(row.tokens)}
                  </TableCell>
                  <TableCell align="right" className="tabular-nums">
                    {fmtUsd(row.cost)}
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

/**
 * Per-user spend drill-down. The user detail view carried a single
 * `tokens_30d` number, which answers neither question an operator has: what is
 * this person costing, and what is driving it.
 */
export default function UserUsageModal({
  userId,
  onClose,
}: {
  userId: string | null;
  onClose: () => void;
}) {
  const token = useSelector(selectToken);
  const [isDarkTheme] = useDarkTheme();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!userId) {
      setData(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    // Drop the previous range's numbers rather than showing them under the
    // newly selected one.
    setData(null);
    adminService
      .getUserUsage(userId, { days }, token)
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled) setData(json);
      })
      .catch(() => !cancelled && setData({ success: false }))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [userId, days, token]);

  const series: Bucket[] = data?.series ?? [];
  const chartData = useMemo(() => {
    const colors = usageColors();
    return {
      labels: series.map((bucket) => formatDate(bucket.bucket)),
      datasets: [
        {
          label: 'Prompt',
          data: series.map((bucket) => bucket.prompt_tokens),
          backgroundColor: colors.prompt,
        },
        {
          label: 'Generated',
          data: series.map((bucket) => bucket.generated_tokens),
          backgroundColor: colors.generated,
        },
      ],
    };
    // isDarkTheme re-resolves the canvas colors when the theme toggles.
  }, [series, isDarkTheme]);

  const totals = data?.totals ?? {};

  return (
    <Modal
      open={userId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={userId ? `Usage · ${userId}` : 'Usage'}
      size="lg"
    >
      <div className="mb-4 flex items-center gap-1">
        {RANGES.map((range) => (
          <Button
            key={range}
            variant={range === days ? 'default' : 'outline'}
            size="sm"
            className="rounded-3xl"
            onClick={() => setDays(range)}
          >
            {range}d
          </Button>
        ))}
      </div>

      {loading ? (
        <Loading />
      ) : data && !data.success ? (
        <LoadError message="Failed to load usage." />
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Cost" value={fmtUsd(totals.cost)} />
            <StatCard label="Tokens" value={fmtNumber(totals.tokens)} />
            <StatCard label="Calls" value={fmtNumber(totals.calls)} />
          </div>

          <div className="border-border h-64 rounded-2xl border px-4 py-3">
            <div className="flex items-center justify-between">
              <p className="text-foreground text-sm font-bold">Daily tokens</p>
              <div id="admin-user-usage-legend" className="flex" />
            </div>
            <div className="relative mt-px h-48 w-full">
              {series.length === 0 ? (
                <p className="text-muted-foreground mt-8 text-sm">
                  No usage in this period.
                </p>
              ) : (
                <UsageChart
                  data={chartData}
                  legendID="admin-user-usage-legend"
                />
              )}
            </div>
          </div>

          <SplitTable title="Model" rows={data?.by_model ?? []} />
          <SplitTable
            title="Flow"
            rows={data?.by_source ?? []}
            labels={FLOW_LABELS}
          />
        </div>
      )}
    </Modal>
  );
}
