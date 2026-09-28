import {
  ChevronDown,
  ChevronRight,
  File,
  Folder,
  type LucideIcon,
} from 'lucide-react';
import { Fragment, useEffect, useMemo, useState } from 'react';

import { useMediaQuery } from '@/hooks';
import { cn } from '@/lib/utils';

import { Button } from '../ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../ui/command';
import { Modal } from '../ui/modal';
import {
  ancestorIds,
  filterNavigatorLeaves,
  findNode,
  type NavigatorNode,
} from './navigatorUtils';

const NO_HIGHLIGHT = '__none__';

/**
 * Tree indent, before the row's icons: a 24px step per level through depth 4
 * (96px), then 12px per further level, so deep rows still step in but keep
 * room for a label in the w-64 column.
 */
function Indent({ depth }: { depth: number }) {
  if (depth <= 0) return null;
  const width = Math.min(depth, 4) * 24 + Math.max(depth - 4, 0) * 12;
  return (
    <span
      aria-hidden
      className="w-(--indent) shrink-0"
      style={{ '--indent': `${width}px` } as React.CSSProperties}
    />
  );
}

/** The folders to expand to show a node: its ancestors, and itself if a folder. */
function revealIds(nodes: NavigatorNode[], id: string): string[] {
  const trail = ancestorIds(nodes, id);
  return findNode(nodes, id)?.kind === 'folder' ? [...trail, id] : trail;
}

export interface SourceNavigatorProps {
  nodes: NavigatorNode[];
  /** The open leaf or folder. */
  selectedId: string | null;
  onSelect: (node: NavigatorNode) => void;
  /** Placeholder and accessible name of the filter ("Filter files"). */
  filterLabel: string;
  /** Shown when the filter matches nothing. */
  emptyLabel: string;
  /** Names the phone picker button and its sheet ("Files", "Pages"). */
  title: string;
  /**
   * `tree`: folders expand and collapse, and a folder can be opened (the file
   * tree). `groups`: each folder is a heading over its pages (the wiki).
   */
  folderMode?: 'tree' | 'groups';
  leafIcon?: LucideIcon;
  /** Layout only. */
  className?: string;
}

/**
 * The navigator column of a source view: a filter field over the source's
 * files or pages, both in one Command, so the arrow keys walk from the field
 * into the list. The open item is `checked`. Below `lg` it collapses into a
 * combobox that opens the same list in a bottom sheet.
 */
export default function SourceNavigator({
  nodes,
  selectedId,
  onSelect,
  filterLabel,
  emptyLabel,
  title,
  folderMode = 'tree',
  leafIcon: LeafIcon = File,
  className,
}: SourceNavigatorProps) {
  const { isDesktop } = useMediaQuery();
  const [query, setQuery] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  // cmdk highlights its first row by default, which reads as hover; start the
  // highlight on the open item instead and let the keys and pointer move it.
  // With nothing open, a value that matches no row: an empty one lets cmdk
  // pick the first row again.
  const [highlight, setHighlight] = useState(selectedId ?? NO_HIGHLIGHT);
  useEffect(() => setHighlight(selectedId ?? NO_HIGHLIGHT), [selectedId]);
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(selectedId ? revealIds(nodes, selectedId) : []),
  );

  // Opening an item elsewhere (a crumb, a table row, a search) reveals it in
  // the tree; an opened folder expands too. Other open folders stay open.
  useEffect(() => {
    if (!selectedId) return;
    const trail = revealIds(nodes, selectedId);
    if (trail.length === 0) return;
    setExpanded((prev) =>
      trail.every((id) => prev.has(id)) ? prev : new Set([...prev, ...trail]),
    );
  }, [nodes, selectedId]);

  const matches = useMemo(
    () => filterNavigatorLeaves(nodes, query),
    [nodes, query],
  );

  const choose = (node: NavigatorNode) => {
    if (node.kind === 'folder' && folderMode === 'tree') {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(node.id) && node.id === selectedId) next.delete(node.id);
        else next.add(node.id);
        return next;
      });
    }
    onSelect(node);
    if (node.kind === 'leaf') {
      setQuery('');
      setSheetOpen(false);
    }
  };

  const leafItem = (node: NavigatorNode, depth: number, meta?: string) => (
    <CommandItem
      key={node.id}
      value={node.id}
      checked={node.id === selectedId}
      onSelect={() => choose(node)}
      title={node.path}
    >
      <Indent depth={depth} />
      <LeafIcon />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{node.label}</span>
        {meta ? (
          <span className="text-muted-foreground truncate text-xs">{meta}</span>
        ) : null}
      </span>
    </CommandItem>
  );

  const treeRows = (list: NavigatorNode[], depth: number): React.ReactNode =>
    list.map((node) => {
      if (node.kind === 'leaf') return leafItem(node, depth);
      const open = expanded.has(node.id);
      const Chevron = open ? ChevronDown : ChevronRight;
      return (
        <Fragment key={node.id}>
          <CommandItem
            value={node.id}
            checked={node.id === selectedId}
            onSelect={() => choose(node)}
            aria-expanded={open}
            title={node.path}
          >
            <Indent depth={depth} />
            <Chevron />
            <Folder className="text-primary" />
            <span className="min-w-0 flex-1 truncate">{node.label}</span>
            {node.count !== undefined ? (
              <span className="text-muted-foreground text-xs tabular-nums">
                {node.count}
              </span>
            ) : null}
          </CommandItem>
          {open ? treeRows(node.children ?? [], depth + 1) : null}
        </Fragment>
      );
    });

  const list = (
    <Command
      shouldFilter={false}
      className="contents"
      loop
      value={highlight}
      onValueChange={setHighlight}
    >
      <CommandInput
        variant="field"
        value={query}
        onValueChange={setQuery}
        placeholder={filterLabel}
        aria-label={filterLabel}
      />
      {/* The column caps its own list; in the phone sheet the Modal body
          scrolls, so the list grows with it (no second scroller). */}
      <CommandList
        className={
          isDesktop ? 'max-h-[70svh] overscroll-contain' : 'max-h-none'
        }
      >
        {query.trim() ? (
          matches.length === 0 ? (
            <CommandEmpty>{emptyLabel}</CommandEmpty>
          ) : (
            <CommandGroup>
              {matches.map(({ node, parentPath }) =>
                leafItem(node, 0, parentPath || undefined),
              )}
            </CommandGroup>
          )
        ) : folderMode === 'groups' ? (
          <>
            <CommandGroup>
              {nodes
                .filter((node) => node.kind === 'leaf')
                .map((node) => leafItem(node, 0))}
            </CommandGroup>
            {nodes
              .filter((node) => node.kind === 'folder')
              .map((folder) => (
                <CommandGroup key={folder.id} heading={folder.label}>
                  {(folder.children ?? []).map((node) => leafItem(node, 0))}
                </CommandGroup>
              ))}
          </>
        ) : (
          <CommandGroup>{treeRows(nodes, 0)}</CommandGroup>
        )}
      </CommandList>
    </Command>
  );

  if (isDesktop) {
    return (
      <nav
        aria-label={title}
        className={cn('flex w-64 shrink-0 flex-col gap-2', className)}
      >
        {list}
      </nav>
    );
  }

  const current = selectedId ? findNode(nodes, selectedId) : undefined;
  return (
    <>
      <Button
        type="button"
        variant="combobox"
        size="field"
        shape="pill"
        className={cn('w-full justify-between', className)}
        onClick={() => setSheetOpen(true)}
        data-placeholder={current ? undefined : ''}
        aria-haspopup="dialog"
      >
        <span className="truncate">{current?.label ?? title}</span>
        <ChevronDown className="opacity-50" />
      </Button>
      <Modal
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        title={title}
        mobileVariant="sheet"
      >
        <div className="flex flex-col gap-2">{list}</div>
      </Modal>
    </>
  );
}
