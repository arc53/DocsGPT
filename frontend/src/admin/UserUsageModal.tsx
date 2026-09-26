import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';

import adminService from '../api/services/adminService';
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
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { selectToken } from '../preferences/preferenceSlice';
import { formatDate } from '../utils/dateTimeUtils';
import { Card } from '@/components/ui/card';
import { LoadingState } from '@/components/ui/loading-state';
import { SectionHeader } from '@/components/ui/section-header';
import StatCard from '@/components/StatCard';
import { LoadError, fmtNumber, fmtUsd } from './AdminUI';
import { useChartPalette } from '../utils/chartUtils';
import UsageChart, { usageColors } from './UsageChart';

type Bucket = {
  bucket: string;
  prompt_tokens: number;
  generated_tokens: number;
  cost: number;
};
type Split = { key: string; tokens: number; cost: number };

const RANGES = [7, 30, 90];

/**
 * Label for a token_usage.source value — what the spend was for.
 *
 * No `schedule` entry: that source marks the run-level rollup row, which the
 * breakdown excludes to avoid double-counting. A scheduled run's individual
 * calls are recorded as `agent_stream`, so its spend appears under Chat.
 */
const FLOW_LABELS: Record<string, string> = {
  agent_stream: 'Chat',
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
                  <TableCell className="text-xs break-all">
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
  // Re-read on every theme change; Chart.js can't read CSS variables.
  const palette = useChartPalette();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

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
  }, [userId, days, token, reloadKey]);

  const series: Bucket[] = data?.series ?? [];
  const chartData = useMemo(() => {
    const colors = usageColors(palette);
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
  }, [series, palette]);

  const totals = data?.totals ?? {};

  return (
    <Modal
      open={userId !== null}
      onOpenChange={(open) => !open && onClose()}
      title={userId ? `Usage · ${userId}` : 'Usage'}
      size="lg"
    >
      <ToggleGroup
        type="single"
        size="sm"
        value={String(days)}
        onValueChange={(value) => value && setDays(Number(value))}
        aria-label="Range"
        className="mb-4"
      >
        {RANGES.map((range) => (
          <ToggleGroupItem key={range} value={String(range)}>
            {range}d
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {loading ? (
        <LoadingState fill="block" />
      ) : data && !data.success ? (
        <LoadError
          message="Failed to load usage."
          onRetry={() => setReloadKey((k) => k + 1)}
        />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-4">
            <StatCard
              variant="outline"
              label="Cost"
              value={fmtUsd(totals.cost)}
            />
            <StatCard
              variant="outline"
              label="Tokens"
              value={fmtNumber(totals.tokens)}
            />
            <StatCard
              variant="outline"
              label="Calls"
              value={fmtNumber(totals.calls)}
            />
          </div>

          <Card variant="outline" padding="default" className="h-66">
            <div className="flex items-center justify-between">
              <SectionHeader as="h3" size="xs" title="Daily tokens" />
              <div id="admin-user-usage-legend" className="flex" />
            </div>
            <div className="relative h-48 w-full">
              {series.length === 0 ? (
                <p className="text-muted-foreground mt-8 text-sm">
                  No usage in this period.
                </p>
              ) : (
                <UsageChart
                  data={chartData}
                  legendID="admin-user-usage-legend"
                  gridColor={palette.border}
                  tickColor={palette.mutedForeground}
                />
              )}
            </div>
          </Card>

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
