import { Fragment, type ReactNode, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';
import { folderRootLabel } from './folderCopy';
import type { Folder, FolderType } from './types';

export type FolderCrumbRowProps = {
  type: FolderType;
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
};

/**
 * The header of an open folder: `Knowledge › Carriers` (or `My agents ›
 * Customer-facing`) on one line, the root and each parent opening its level
 * (parents truncate first, the root stays whole, as in a source view's
 * PathHeader), the count line under it, and the page's buttons with the
 * folder's ⋯ last on the row. On a phone the ⋯ stays at the end of the crumb
 * line and the buttons take their own row under the count line, so neither
 * overflows.
 */
export default function FolderCrumbRow({
  type,
  trail,
  onNavigate,
  meta,
  actions,
  menu,
}: FolderCrumbRowProps) {
  const { t } = useTranslation();
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
  const rootLabel = folderRootLabel(t, type);

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
    </div>
  );
}
