import {
  Bot,
  Database,
  type LucideIcon,
  MessageSquareText,
  Wrench,
} from 'lucide-react';
import { Fragment, type ReactNode, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Link } from 'react-router-dom';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';
import { Button } from '../ui/button';
import { folderCount, folderOtherKinds, folderRootLabel } from './folderCopy';
import { folderPagePath } from './folderTree';
import { selectFoldersInTeam } from './folderWorkspace';
import type { Folder, ItemKind } from './types';

/** The icon of each kind's page, for the "Also in this folder" links. */
const KIND_ICONS: Record<ItemKind, LucideIcon> = {
  agent: Bot,
  source: Database,
  tool: Wrench,
  prompt: MessageSquareText,
};

export type FolderCrumbRowProps = {
  /** The page's kind: names the root and is left out of "Also in this folder". */
  kind?: ItemKind;
  /** The open folder's trail, top level first, the open folder last. */
  trail: Folder[];
  /** Open a folder from the trail, or the root (null). */
  onNavigate: (folderId: string | null) => void;
  /** The folder's facts under the crumbs ("3 sources · 1 folder"). */
  meta?: ReactNode;
  /** The page's buttons for this place (New folder, Add knowledge). */
  actions?: ReactNode;
  /** The folder's ⋯ (`ActionMenu size="toolbar"`), last on the row. */
  menu?: ReactNode;
  /**
   * "Also in this folder": a link per other kind the open folder holds, to
   * the same folder on that kind's page (default on).
   */
  alsoLinks?: boolean;
};

/**
 * The header of an open folder: `Knowledge › Carriers` (or `My agents ›
 * Customer-facing`, `Prompts › Onboarding`) on one line, the root and each
 * parent opening its level (parents truncate first, the root stays whole, as
 * in a source view's PathHeader), the count line under it, "Also in this
 * folder" with a link per other kind it holds, and the page's buttons with
 * the folder's ⋯ last on the row. On a phone the ⋯ stays at the end of the
 * crumb line and the buttons take their own row under the count line, so
 * neither overflows.
 */
export default function FolderCrumbRow({
  kind: kindProp,
  trail,
  onNavigate,
  meta,
  actions,
  menu,
  alsoLinks = true,
}: FolderCrumbRowProps) {
  const { t } = useTranslation();
  const kind = kindProp ?? 'agent';
  const inTeam = useSelector(selectFoldersInTeam);
  const open = trail.length > 0 ? trail[trail.length - 1] : null;
  const others = open && alsoLinks ? folderOtherKinds(open, kind) : [];
  // A crumb step replaces the focused button (it becomes the current crumb),
  // which would drop focus to <body>; once the trail changes, focus lands on
  // the new current crumb instead (as PathHeader does).
  const currentRef = useRef<HTMLSpanElement>(null);
  const refocus = useRef(false);
  const key = trail.map((folder) => folder.id).join('/');
  useEffect(() => {
    if (!refocus.current) return;
    refocus.current = false;
    currentRef.current?.focus();
  }, [key]);
  const step = (folderId: string | null) => {
    refocus.current = true;
    onNavigate(folderId);
  };
  const rootLabel = folderRootLabel(t, kind, { team: inTeam });

  return (
    <div
      data-slot="folder-crumb-row"
      className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]"
    >
      <div className="col-start-1 row-start-1 flex min-h-9.5 min-w-0 items-center">
        <Breadcrumb className="min-w-0">
          <BreadcrumbList>
            <BreadcrumbItem>
              {trail.length === 0 ? (
                <BreadcrumbPage ref={currentRef} tabIndex={-1}>
                  {rootLabel}
                </BreadcrumbPage>
              ) : (
                <BreadcrumbLink asChild>
                  <button type="button" onClick={() => step(null)}>
                    {rootLabel}
                  </button>
                </BreadcrumbLink>
              )}
            </BreadcrumbItem>
            {trail.map((folder, index) => (
              <Fragment key={folder.id}>
                <BreadcrumbSeparator className="shrink-0" />
                <BreadcrumbItem>
                  {index === trail.length - 1 ? (
                    <BreadcrumbPage ref={currentRef} tabIndex={-1}>
                      {folder.name}
                    </BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink asChild>
                      <button
                        type="button"
                        title={folder.name}
                        onClick={() => step(folder.id)}
                      >
                        {folder.name}
                      </button>
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </Fragment>
            ))}
          </BreadcrumbList>
        </Breadcrumb>
      </div>
      {menu ? (
        <div className="col-start-2 row-start-1 flex sm:col-start-3">
          {menu}
        </div>
      ) : null}
      {meta ? (
        <p className="text-muted-foreground col-span-2 col-start-1 row-start-2 text-sm sm:col-span-1">
          {meta}
        </p>
      ) : null}
      {actions ? (
        <div className="col-span-2 col-start-1 row-start-3 flex flex-wrap items-center gap-2 sm:col-span-1 sm:col-start-2 sm:row-start-1">
          {actions}
        </div>
      ) : null}
      {open && others.length > 0 ? (
        <div
          data-slot="folder-also"
          className="text-muted-foreground col-span-2 col-start-1 row-start-4 flex flex-wrap items-center gap-2 text-xs sm:col-span-3 sm:row-start-3"
        >
          <span>{t('workspace.folders.alsoInFolder')}</span>
          {others.map((entry) => {
            const Icon = KIND_ICONS[entry.kind];
            return (
              <Button
                key={entry.kind}
                asChild
                variant="outline"
                size="xs"
                shape="pill"
              >
                <Link to={folderPagePath(entry.kind, open.id)}>
                  <Icon className="text-muted-foreground" aria-hidden="true" />
                  {folderCount(t, entry.kind, entry.count)}
                </Link>
              </Button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
