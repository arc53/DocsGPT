import {
  Brain,
  Download,
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
import { useState } from 'react';
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

/** The muted line under an artifact's title: its kind, then its version. */
export function useArtifactMeta() {
  const { t } = useTranslation();
  return (item: ArtifactCardItem) =>
    item.version
      ? `${t(KIND_LABEL_KEY[item.kind])} · ${t('conversation.artifacts.version', { version: item.version })}`
      : t(KIND_LABEL_KEY[item.kind]);
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
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const meta = useArtifactMeta();
  const [downloading, setDownloading] = useState(false);
  const Icon = KIND_ICON[item.kind];

  const download = async () => {
    setDownloading(true);
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
      setDownloading(false);
    }
  };

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
          onClick={() => onOpen(item)}
          title={item.title}
          className="text-foreground block w-full cursor-pointer truncate text-left text-sm font-medium outline-none after:absolute after:inset-0 after:rounded-2xl"
        >
          {item.title}
        </button>
        <p className="text-muted-foreground truncate text-xs">{meta(item)}</p>
      </div>
      {item.downloadable && (
        <IconButton
          label={t('conversation.artifacts.download', { title: item.title })}
          icon={Download}
          variant="ghost-muted"
          size="icon-sm"
          shape="pill"
          loading={downloading}
          onClick={download}
          className="relative z-10"
        />
      )}
    </div>
  );
}

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
  className,
}: {
  items: ArtifactCardItem[];
  /** The artifact the side panel shows; a card naming another version of it is not open. */
  open?: { id: string; version?: number } | null;
  onOpen: (item: ArtifactCardItem) => void;
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    // The answer column is a wrapping flex box, where a container-query
    // element has no width of its own: the full-width box gives the query
    // a definite width, or the cards' height is laid out as if stacked.
    <div className="w-full min-w-0">
      <div className={cn('@container', className)}>
        <ul className="grid max-w-3xl grid-cols-1 gap-2 @min-[33rem]:grid-cols-2">
          {items.map((item) => (
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
        </ul>
      </div>
    </div>
  );
}
