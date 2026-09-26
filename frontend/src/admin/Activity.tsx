import { ChevronDown, ChevronRight, Download } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import adminService, {
  type ActivityFilters,
} from '../api/services/adminService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { IconButton } from '../components/ui/icon-button';
import SearchInput from '../components/SearchInput';
import {
  DescriptionItem,
  DescriptionList,
} from '../components/ui/description-list';
import { LoadingState } from '../components/ui/loading-state';
import { MultiSelect } from '../components/ui/multi-select';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import { Pagination } from '../components/ui/pagination';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { selectToken } from '../preferences/preferenceSlice';
import {
  LoadError,
  categoryTone,
  eventLabel,
  eventTone,
  fmtDate,
  fmtNumber,
  fmtRelative,
  isLoopback,
  outcomeLabel,
  outcomeTone,
} from './AdminUI';
import { cn } from '@/lib/utils';

type ActivityRow = {
  feed: string;
  id: string;
  event: string;
  category: string;
  actor_id: string | null;
  target_id: string | null;
  ip: string | null;
  user_agent: string | null;
  outcome: string | null;
  detail: Record<string, unknown> | null;
  created_at: string | null;
};

type Catalogue = {
  events: { event: string; category: string }[];
  categories: string[];
};

const PAGE_SIZE = 50;

/** Quick ranges, in days. `0` means "no lower bound". */
const RANGES: { label: string; days: number }[] = [
  { label: '24h', days: 1 },
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: 'All', days: 0 },
];

function sinceFor(days: number): string | undefined {
  if (days <= 0) return undefined;
  return new Date(Date.now() - days * 86400000).toISOString();
}

/** One detail value, rendered as a readable line rather than raw JSON. */
function DetailRow({ label, value }: { label: string; value: unknown }) {
  const text =
    typeof value === 'object' && value !== null
      ? JSON.stringify(value)
      : String(value);
  return (
    <DescriptionItem label={label} mono>
      {text}
    </DescriptionItem>
  );
}

/**
 * The expanded row. auth_events captures `metadata` and `user_agent` on every
 * insert and the table showed neither, so "Admin revoked · user-42" never said
 * who revoked it. Everything the feed carries lands here.
 */
function RowDetail({ row }: { row: ActivityRow }) {
  const detail = row.detail ?? {};
  const entries = Object.entries(detail);
  return (
    <div className="bg-muted rounded-lg px-4 py-3">
      <DescriptionList layout="columns" size="xs">
        <DetailRow label="Event" value={row.event} />
        <DetailRow label="Journal" value={row.feed} />
        {row.actor_id ? <DetailRow label="Actor" value={row.actor_id} /> : null}
        {row.target_id ? (
          <DetailRow label="Affected user" value={row.target_id} />
        ) : null}
        {row.outcome ? <DetailRow label="Outcome" value={row.outcome} /> : null}
        {row.ip ? <DetailRow label="IP" value={row.ip} /> : null}
        {row.user_agent ? (
          <DetailRow label="User agent" value={row.user_agent} />
        ) : null}
        <DetailRow label="Recorded" value={fmtDate(row.created_at)} />
      </DescriptionList>
      {entries.length > 0 ? (
        <div className="border-border mt-2 border-t pt-2">
          <DescriptionList layout="columns" size="xs">
            {entries.map(([key, value]) => (
              <DetailRow key={key} label={key} value={value} />
            ))}
          </DescriptionList>
        </div>
      ) : null}
    </div>
  );
}

export default function Activity() {
  const token = useSelector(selectToken);
  const [searchParams] = useSearchParams();

  // Deep links from Overview land here pre-filtered (?event=oidc_login_denied).
  const initialEvent = searchParams.get('event');

  const [rows, setRows] = useState<ActivityRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);

  const [categories, setCategories] = useState<string[]>([]);
  const [events, setEvents] = useState<string[]>(
    initialEvent ? [initialEvent] : [],
  );
  const [rangeDays, setRangeDays] = useState(30);
  const [searchDraft, setSearchDraft] = useState('');
  const [search, setSearch] = useState('');

  /**
   * Narrowing the feed invalidates whatever page you were on, so every filter
   * setter resets it. Resetting in an effect instead would fetch the old page
   * against the new filters first, then fetch again.
   */
  const withPageReset =
    <T,>(set: (value: T) => void) =>
    (value: T) => {
      setPage(1);
      set(value);
    };

  const filters: ActivityFilters = useMemo(
    () => ({
      category: categories.length ? categories : undefined,
      event: events.length ? events : undefined,
      since: sinceFor(rangeDays),
      search: search || undefined,
    }),
    [categories, events, rangeDays, search],
  );

  useEffect(() => {
    let cancelled = false;
    adminService
      .getActivityEvents(token)
      .then((res) => res.json())
      .then((json) => {
        if (!cancelled && json?.success) setCatalogue(json);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token]);

  // Monotonic request id: a response only lands if no newer request was
  // issued meanwhile, so an out-of-order reply cannot leave the table showing
  // a different filter combination than the controls. Mirrors the guard in
  // settings/Analytics.
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setFailed(false);
    try {
      const res = await adminService.getActivity(
        { ...filters, page, page_size: PAGE_SIZE },
        token,
      );
      const json = await res.json().catch(() => ({}));
      if (id !== requestId.current) return;
      setRows(json.activity ?? []);
      setTotal(json.total ?? 0);
      setFailed(!res.ok || json.success === false);
    } catch {
      if (id === requestId.current) setFailed(true);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [token, page, filters]);

  useEffect(() => {
    load();
  }, [load]);

  const exportAs = async (format: 'csv' | 'ndjson') => {
    setExporting(true);
    try {
      const res = await adminService.exportActivity(filters, format, token);
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `docsgpt-activity.${format}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const eventOptions = useMemo(
    () =>
      (catalogue?.events ?? []).map(({ event }) => ({
        value: event,
        label: eventLabel(event),
      })),
    [catalogue],
  );
  const categoryOptions = useMemo(
    () =>
      (catalogue?.categories ?? []).map((category) => ({
        value: category,
        label: category.charAt(0).toUpperCase() + category.slice(1),
      })),
    [catalogue],
  );

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasFilters =
    categories.length > 0 || events.length > 0 || search !== '';

  const applySearch = () => withPageReset(setSearch)(searchDraft.trim());

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="w-full max-w-xs">
          <SearchInput
            label="Search user, IP or detail"
            value={searchDraft}
            onChange={(e) => setSearchDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && applySearch()}
            onBlur={applySearch}
          />
        </div>
        <MultiSelect
          options={categoryOptions}
          selected={categories}
          onChange={withPageReset(setCategories)}
          placeholder="All categories"
          className="w-48"
        />
        <MultiSelect
          options={eventOptions}
          selected={events}
          onChange={withPageReset(setEvents)}
          placeholder="All events"
          searchPlaceholder="Find an event"
          className="w-56"
        />
        <ToggleGroup
          type="single"
          size="sm"
          value={String(rangeDays)}
          onValueChange={(value) =>
            value && withPageReset(setRangeDays)(Number(value))
          }
          aria-label="Range"
        >
          {RANGES.map((range) => (
            <ToggleGroupItem key={range.label} value={String(range.days)}>
              {range.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {hasFilters ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setPage(1);
              setCategories([]);
              setEvents([]);
              setSearchDraft('');
              setSearch('');
            }}
          >
            Clear
          </Button>
        ) : null}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={exporting}
            onClick={() => exportAs('csv')}
          >
            <Download />
            CSV
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={exporting}
            onClick={() => exportAs('ndjson')}
          >
            <Download />
            NDJSON
          </Button>
        </div>
      </div>

      {loading ? (
        <LoadingState fill="block" />
      ) : failed ? (
        <LoadError message="Failed to load activity." onRetry={load} />
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground mt-8 text-sm">No activity.</p>
      ) : (
        <>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader className="w-8" />
                  <TableHeader>Event</TableHeader>
                  <TableHeader>Category</TableHeader>
                  <TableHeader>Actor</TableHeader>
                  <TableHeader>Affected</TableHeader>
                  <TableHeader>IP</TableHeader>
                  <TableHeader>When</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row, idx) => {
                  const key = `${row.feed}:${row.id}`;
                  const isOpen = expanded === key;
                  // De-emphasize an actor repeated from the row above (ditto),
                  // so distinct actors stand out in a long single-user stream.
                  const repeat =
                    idx > 0 && rows[idx - 1].actor_id === row.actor_id;
                  return [
                    <TableRow key={key}>
                      <TableCell>
                        <IconButton
                          variant="ghost-muted"
                          size="icon-xs"
                          aria-expanded={isOpen}
                          label={
                            isOpen
                              ? `Hide details for ${eventLabel(row.event)}`
                              : `Show details for ${eventLabel(row.event)}`
                          }
                          icon={isOpen ? ChevronDown : ChevronRight}
                          onClick={() => setExpanded(isOpen ? null : key)}
                        />
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Badge variant={eventTone(row.event)}>
                            {eventLabel(row.event)}
                          </Badge>
                          {row.outcome ? (
                            <Badge variant={outcomeTone(row.outcome)}>
                              {outcomeLabel(row.outcome)}
                            </Badge>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={categoryTone(row.category)}>
                          {row.category}
                        </Badge>
                      </TableCell>
                      <TableCell
                        className={cn(
                          'font-mono text-xs',
                          repeat ? 'text-muted-foreground/50' : '',
                        )}
                      >
                        {repeat ? '〃' : (row.actor_id ?? '—')}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {row.target_id && row.target_id !== row.actor_id
                          ? row.target_id
                          : '—'}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {row.ip === null ? (
                          <span className="text-muted-foreground text-xs">
                            —
                          </span>
                        ) : isLoopback(row.ip) ? (
                          <span className="text-muted-foreground text-xs">
                            local
                          </span>
                        ) : (
                          <span className="font-mono text-xs">{row.ip}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        <span title={fmtDate(row.created_at)}>
                          {fmtRelative(row.created_at)}
                        </span>
                      </TableCell>
                    </TableRow>,
                    isOpen ? (
                      <TableRow key={`${key}:detail`}>
                        <TableCell colSpan={7}>
                          <RowDetail row={row} />
                        </TableCell>
                      </TableRow>
                    ) : null,
                  ];
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <Pagination
            page={page}
            pageCount={totalPages}
            onPageChange={setPage}
            summary={`${fmtNumber(total)} events`}
          />
        </>
      )}
    </div>
  );
}
