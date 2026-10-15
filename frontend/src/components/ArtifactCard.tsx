import {
  Brain,
  ChevronRight,
  Download,
  Layers,
  File,
  FileText,
  FileType,
  Globe,
  Image as ImageIcon,
  ListTodo,
  NotebookPen,
  Presentation,
  Sheet,
  Table,
  type LucideIcon,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import { IconButton } from '@/components/ui/icon-button';
import { cn } from '@/lib/utils';

import userService from '../api/services/userService';
import type {
  ArtifactCardItem,
  ArtifactKind,
} from '../conversation/artifactCards';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { triggerResponseDownload } from './artifactViewUtils';

const KIND_ICON: Record<ArtifactKind, LucideIcon> = {
  page: Globe,
  pdf: FileText,
  slides: Presentation,
  document: FileType,
  spreadsheet: Sheet,
  data: Table,
  image: ImageIcon,
  note: NotebookPen,
  todo: ListTodo,
  memory: Brain,
  file: File,
};

// A note, todo or memory reuses the artifact panel's own type names.
const KIND_LABEL_KEY: Record<ArtifactKind, string> = {
  page: 'conversation.artifacts.kind.page',
  pdf: 'conversation.artifacts.kind.pdf',
  slides: 'conversation.artifacts.kind.slides',
  document: 'conversation.artifacts.kind.document',
  spreadsheet: 'conversation.artifacts.kind.spreadsheet',
  data: 'conversation.artifacts.kind.data',
  image: 'conversation.artifacts.kind.image',
  file: 'conversation.artifacts.kind.file',
  note: 'components.artifact.types.note',
  todo: 'components.artifact.types.todoList',
  memory: 'components.artifact.types.memory',
};

/** The kind icon an artifact card or list row leads with. */
export function artifactKindIcon(kind: ArtifactKind): LucideIcon {
  return KIND_ICON[kind];
}

/** An artifact kind's name ("HTML page", "Spreadsheet", "Note"). */
export function useArtifactKindLabel() {
  const { t } = useTranslation();
  return (kind: ArtifactKind) => t(KIND_LABEL_KEY[kind]);
}

/** The muted line under an artifact's title: its kind, then its version. */
export function useArtifactMeta() {
  const { t } = useTranslation();
  return (item: ArtifactCardItem) =>
    item.version
      ? `${t(KIND_LABEL_KEY[item.kind])} · ${t('conversation.artifacts.version', { version: item.version })}`
      : t(KIND_LABEL_KEY[item.kind]);
}

/**
 * Saves an artifact's file, the version its card or row names; a failure is
 * a destructive toast (DESIGN.md › Where a message lives).
 *
 * Returns:
 *   `download(item)` and the id of the one being saved.
 */
export function useArtifactDownload() {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

  const download = async (item: ArtifactCardItem) => {
    setDownloadingId(item.id);
    try {
      const response = await userService.downloadArtifact(
        item.id,
        token,
        item.version,
        'url',
      );
      const ok = await triggerResponseDownload(
        response,
        item.filename || item.title,
      );
      if (!ok) throw new Error('download failed');
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('components.artifact.downloadFailed'),
        }),
      );
    } finally {
      setDownloadingId(null);
    }
  };

  return { download, downloadingId };
}

/**
 * One artifact under an answer: its kind icon on the brand soft fill, the
 * title, the kind and version, and Download for a file. The whole card opens
 * the artifact in the side panel through a stretched button named by the
 * title (DESIGN.md › A clickable card that holds a link); Download sits above
 * it. `open` marks the card whose artifact the panel shows (the open-row
 * rule: `bg-secondary`).
 *
 * Args:
 *   item: The artifact.
 *   open: True while the side panel shows it.
 *   onOpen: Opens it in the side panel.
 */
export function ArtifactCard({
  item,
  open = false,
  onOpen,
}: {
  item: ArtifactCardItem;
  open?: boolean;
  onOpen: (item: ArtifactCardItem) => void;
}) {
  const { t } = useTranslation();
  const meta = useArtifactMeta();
  const { download, downloadingId } = useArtifactDownload();
  const downloading = downloadingId === item.id;

  return (
    <CardFrame
      icon={KIND_ICON[item.kind]}
      title={item.title}
      meta={meta(item)}
      open={open}
      onClick={() => onOpen(item)}
      trailing={
        item.downloadable ? (
          <IconButton
            label={t('conversation.artifacts.download', { title: item.title })}
            icon={Download}
            variant="ghost-muted"
            size="icon-sm"
            shape="pill"
            loading={downloading}
            onClick={() => download(item)}
            className="relative z-10"
          />
        ) : null
      }
    />
  );
}

/**
 * The box every answer artifact card shares: the kind icon on the brand soft
 * fill, a stretched button named by the title, a muted meta line outside it
 * and a trailing control above it (DESIGN.md › A clickable card that holds a
 * link). `open` is the open-row fill.
 */
function CardFrame({
  icon: Icon,
  title,
  meta,
  open,
  onClick,
  trailing,
}: {
  icon: LucideIcon;
  title: string;
  meta: string;
  open: boolean;
  onClick: () => void;
  trailing: ReactNode;
}) {
  return (
    <div
      data-slot="artifact-card"
      className={cn(
        'relative flex min-w-0 items-center gap-3 rounded-2xl p-3 transition-colors',
        'has-[[data-artifact-open]:focus-visible]:ring-ring/50 has-[[data-artifact-open]:focus-visible]:ring-3',
        open ? 'bg-secondary' : 'bg-answer-surface hover:bg-accent',
      )}
    >
      <span
        aria-hidden
        className="bg-secondary text-secondary-foreground flex size-10 shrink-0 items-center justify-center rounded-xl"
      >
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          data-artifact-open
          aria-current={open || undefined}
          onClick={onClick}
          title={title}
          className="text-foreground block w-full cursor-pointer truncate text-left text-sm font-medium outline-none after:absolute after:inset-0 after:rounded-2xl"
        >
          {title}
        </button>
        <p className="text-muted-foreground truncate text-xs">{meta}</p>
      </div>
      {trailing}
    </div>
  );
}

/**
 * The last slot when an answer made more artifacts than fit: the count of the
 * rest, opening the answer's full list in the side panel. A chevron, not
 * Download, because it opens a list rather than a file.
 */
function MoreArtifactsCard({
  hidden,
  total,
  open,
  onClick,
}: {
  hidden: number;
  total: number;
  open: boolean;
  onClick: () => void;
}) {
  const { t } = useTranslation();
  return (
    <CardFrame
      icon={Layers}
      title={t('conversation.artifacts.more', { count: hidden })}
      meta={t('conversation.artifacts.showAll', { count: total })}
      open={open}
      onClick={onClick}
      trailing={
        <ChevronRight
          aria-hidden
          className="text-muted-foreground mr-2 size-4 shrink-0"
        />
      }
    />
  );
}

/** Cards an answer shows before the rest fold into “N more files”. */
export const ARTIFACT_CARD_SLOTS = 4;

/**
 * An answer's artifact cards: two columns once its own column fits two
 * (a container query, so a narrow column such as the builder preview stacks
 * them on any screen), one below that, at most 768px wide.
 *
 * Args:
 *   items: The cards, in the order to show them.
 *   open: The artifact (and version) the side panel shows.
 *   onOpen: Opens one in the side panel.
 *   className: Layout on the wrapper (the answer column's margins).
 */
export function ArtifactCardList({
  items,
  open,
  onOpen,
  onShowAll,
  showAllOpen = false,
  className,
}: {
  items: ArtifactCardItem[];
  /** The artifact the side panel shows; a card naming another version of it is not open. */
  open?: { id: string; version?: number } | null;
  onOpen: (item: ArtifactCardItem) => void;
  /** Opens the answer's full list; without it every card shows. */
  onShowAll?: () => void;
  /** True while the side panel shows this answer's list. */
  showAllOpen?: boolean;
  className?: string;
}) {
  if (items.length === 0) return null;
  // Past four, the first three and a fourth card for the rest.
  const folded = Boolean(onShowAll) && items.length > ARTIFACT_CARD_SLOTS;
  const shown = folded ? items.slice(0, ARTIFACT_CARD_SLOTS - 1) : items;
  return (
    // The answer column is a wrapping flex box, where a container-query
    // element has no width of its own: the full-width box gives the query
    // a definite width, or the cards' height is laid out as if stacked.
    <div className="w-full min-w-0">
      <div className={cn('@container', className)}>
        <ul className="grid max-w-3xl grid-cols-1 gap-2 @min-[33rem]:grid-cols-2">
          {shown.map((item) => (
            <li key={item.id} className="min-w-0">
              <ArtifactCard
                item={item}
                open={
                  !!open &&
                  item.id === open.id &&
                  (open.version === undefined || item.version === open.version)
                }
                onOpen={onOpen}
              />
            </li>
          ))}
          {folded && onShowAll ? (
            <li className="min-w-0">
              <MoreArtifactsCard
                hidden={items.length - shown.length}
                total={items.length}
                open={showAllOpen}
                onClick={onShowAll}
              />
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
