import { useCallback, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { useSearchParams } from 'react-router-dom';

import adminService from '../api/services/adminService';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
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
import {
  Loading,
  Pill,
  eventLabel,
  eventTone,
  fmtDate,
  fmtNumber,
  fmtRelative,
  isLoopback,
} from './AdminUI';

type Event = {
  id: string;
  user_id: string;
  event: string;
  ip?: string;
  created_at?: string;
};

const PAGE_SIZE = 50;

export default function Audit() {
  const token = useSelector(selectToken);
  const [searchParams] = useSearchParams();
  const initialEvent = searchParams.get('event') ?? '';
  const [events, setEvents] = useState<Event[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [eventFilter, setEventFilter] = useState(initialEvent);
  const [userFilter, setUserFilter] = useState('');
  const [search, setSearch] = useState({ event: initialEvent, user_id: '' });
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await adminService.getAudit(
        {
          page,
          page_size: PAGE_SIZE,
          event: search.event || undefined,
          user_id: search.user_id || undefined,
        },
        token,
      );
      const json = await res.json().catch(() => ({}));
      setEvents(json.events ?? []);
      setTotal(json.total ?? 0);
    } finally {
      setLoading(false);
    }
  }, [token, page, search]);

  useEffect(() => {
    load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const applyFilters = () => {
    setPage(1);
    setSearch({ event: eventFilter.trim(), user_id: userFilter.trim() });
  };

  return (
    <div className="mt-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          placeholder="Event (e.g. oidc_login_denied)"
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
          className="max-w-xs"
        />
        <Input
          placeholder="User id"
          value={userFilter}
          onChange={(e) => setUserFilter(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
          className="max-w-xs"
        />
        <Button variant="outline" size="sm" onClick={applyFilters}>
          Filter
        </Button>
        {(search.event || search.user_id) && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setEventFilter('');
              setUserFilter('');
              setPage(1);
              setSearch({ event: '', user_id: '' });
            }}
          >
            Clear
          </Button>
        )}
      </div>

      {loading ? (
        <Loading />
      ) : events.length === 0 ? (
        <p className="text-muted-foreground mt-8 text-sm">No events.</p>
      ) : (
        <>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeader>Event</TableHeader>
                  <TableHeader>User</TableHeader>
                  <TableHeader>IP</TableHeader>
                  <TableHeader>When</TableHeader>
                </TableRow>
              </TableHead>
              <TableBody>
                {events.map((ev, idx) => {
                  // De-emphasize a user id repeated from the row above (ditto),
                  // so distinct users stand out in a long single-user stream.
                  const repeat =
                    idx > 0 && events[idx - 1].user_id === ev.user_id;
                  return (
                    <TableRow key={ev.id}>
                      <TableCell>
                        <Pill tone={eventTone(ev.event)}>
                          {eventLabel(ev.event)}
                        </Pill>
                      </TableCell>
                      <TableCell
                        className={`font-mono text-[13px] ${
                          repeat ? 'text-muted-foreground/50' : ''
                        }`}
                      >
                        {repeat ? '〃' : ev.user_id}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {isLoopback(ev.ip) ? (
                          <span className="text-muted-foreground text-xs">
                            local
                          </span>
                        ) : (
                          <span className="font-mono text-[13px]">
                            {ev.ip ?? '—'}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-muted-foreground whitespace-nowrap">
                        <span title={fmtDate(ev.created_at)}>
                          {fmtRelative(ev.created_at)}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
          <div className="mt-4 flex items-center justify-between">
            <p className="text-muted-foreground text-sm">
              {fmtNumber(total)} events · page {page} of {totalPages}
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
    </div>
  );
}
