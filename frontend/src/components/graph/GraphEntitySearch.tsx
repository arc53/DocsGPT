import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../../api/services/userService';
import { useDebouncedValue } from '../../hooks';
import { selectToken } from '../../preferences/preferenceSlice';
import SearchInput from '../SearchInput';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from '../ui/command';
import { EmptyState } from '../ui/empty-state';
import { LoadingState } from '../ui/loading-state';
import { Popover, PopoverAnchor, PopoverContent } from '../ui/popover';
import type { FoldedGraphTypes, GraphNodeSummary } from '../graphViewUtils';
import type { GraphNodeRef } from './GraphNodePanel';
import { GraphTypeDot, useGraphTypeLabel } from './GraphTypeDot';

const SEARCH_PAGE_SIZE = 8;

/**
 * "Find an entity": searches every node of the source by name (not only the
 * loaded overview) and selects the pick. The results are a Popover + Command
 * anchored under the field; arrows and Enter drive it from the field.
 */
export default function GraphEntitySearch({
  docId,
  fold,
  onPick,
}: {
  docId: string;
  fold: FoldedGraphTypes;
  onPick: (node: GraphNodeRef) => void;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const labelOf = useGraphTypeLabel(fold);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [hits, setHits] = useState<GraphNodeSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState('');
  const anchorRef = useRef<HTMLDivElement>(null);
  const debounced = useDebouncedValue(query.trim(), 250);

  useEffect(() => {
    if (!debounced) {
      setHits([]);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    userService
      .getSourceGraphNodes(
        docId,
        { q: debounced, perPage: SEARCH_PAGE_SIZE },
        token,
      )
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((body) => {
        if (cancelled) return;
        const nodes: GraphNodeSummary[] = body?.nodes ?? [];
        setHits(nodes);
        setActive(nodes[0]?.id ?? '');
      })
      .catch((error) => {
        if (cancelled) return;
        console.error('Error searching graph nodes:', error);
        setHits([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, debounced, token]);

  const pick = (hit: GraphNodeSummary) => {
    setQuery('');
    setOpen(false);
    onPick({ id: hit.id, name: hit.name, type: hit.type });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      if (open) {
        event.preventDefault();
        setOpen(false);
      }
      return;
    }
    if (!hits.length) return;
    const index = hits.findIndex((hit) => hit.id === active);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      const step = event.key === 'ArrowDown' ? 1 : -1;
      const next = (index + step + hits.length) % hits.length;
      setActive(hits[next].id);
    } else if (event.key === 'Enter' && open) {
      event.preventDefault();
      // Still debouncing: the listed hits belong to the previous query.
      if (query.trim() !== debounced) return;
      const hit = hits[index] ?? hits[0];
      if (hit) pick(hit);
    }
  };

  const showPopover = open && query.trim() !== '';
  // Still typing, or the request is out: don't flash "No entities found".
  const pending = loading || query.trim() !== debounced;

  return (
    <Popover open={showPopover} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div ref={anchorRef} className="w-full sm:w-72">
          <SearchInput
            label={t('settings.sources.graphrag.view.findEntity')}
            value={query}
            role="combobox"
            aria-expanded={showPopover}
            aria-autocomplete="list"
            onChange={(event) => {
              setQuery(event.target.value);
              setOpen(true);
            }}
            onFocus={() => {
              if (query.trim()) setOpen(true);
            }}
            onKeyDown={onKeyDown}
          />
        </div>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) p-0"
        onOpenAutoFocus={(event) => event.preventDefault()}
        onInteractOutside={(event) => {
          // A click back in the field keeps the list open.
          if (anchorRef.current?.contains(event.target as Node)) {
            event.preventDefault();
          }
        }}
      >
        <Command shouldFilter={false} value={active} onValueChange={setActive}>
          <CommandList>
            {pending && hits.length === 0 ? (
              <LoadingState fill="block" size="sm" />
            ) : (
              <CommandEmpty>
                <EmptyState
                  size="xs"
                  illustration="none"
                  title={t('settings.sources.graphrag.view.noEntities')}
                />
              </CommandEmpty>
            )}
            {hits.length ? (
              <CommandGroup>
                {hits.map((hit) => (
                  <CommandItem
                    key={hit.id}
                    value={hit.id}
                    onSelect={() => pick(hit)}
                  >
                    <GraphTypeDot fold={fold} type={hit.type} />
                    <span className="min-w-0 flex-1 truncate" title={hit.name}>
                      {hit.name}
                    </span>
                    <span className="text-muted-foreground max-w-[40%] truncate text-xs">
                      {labelOf(hit.type)}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ) : null}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
