import type { ReactNode } from 'react';
import { Fragment, useEffect, useRef } from 'react';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';

export type Crumb = { label: string; onSelect?: () => void };

/**
 * The header of every source view (files, chunks, wiki, graph): the crumbs
 * (Sources, the source, its folders, the open file and chunk), the source
 * kind's badge, and actions (Test retrieval, the kind's primary action) on
 * the right; the byline (the source's counts and a one-sentence explainer)
 * goes under the row. Up one level is a crumb, as on the Tools and Teams
 * detail pages (DetailBreadcrumb), never a back arrow. The crumbs stay on one
 * line: parents truncate, and the last crumb is the current one.
 */
export default function PathHeader({
  root,
  segments = [],
  badge,
  byline,
  actions,
}: {
  /** The first crumb: Sources, or the source when a host draws Sources. */
  root: Crumb;
  segments?: Crumb[];
  /** The source kind (a neutral Badge), after the crumbs. */
  badge?: ReactNode;
  /** Muted meta line under the row. */
  byline?: ReactNode;
  actions?: ReactNode;
}) {
  const crumbs = [root, ...segments];

  // A crumb step replaces the focused button (it becomes the current crumb,
  // or goes), which would drop focus to <body>. Once the trail changes,
  // focus lands on the new current crumb instead.
  const currentRef = useRef<HTMLSpanElement>(null);
  const refocusRef = useRef(false);
  const trail = crumbs.map((crumb) => crumb.label).join('/');
  useEffect(() => {
    if (!refocusRef.current) return;
    refocusRef.current = false;
    currentRef.current?.focus();
  }, [trail]);
  const select = (crumb: Crumb) => {
    refocusRef.current = true;
    crumb.onSelect?.();
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-9.5 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex w-full min-w-0 items-center gap-3 sm:w-auto">
          <Breadcrumb className="min-w-0">
            <BreadcrumbList>
              {crumbs.map((crumb, index) => {
                const isLast = index === crumbs.length - 1;
                return (
                  <Fragment key={`${index}-${crumb.label}`}>
                    {index > 0 ? (
                      <BreadcrumbSeparator className="shrink-0" />
                    ) : null}
                    <BreadcrumbItem>
                      {isLast ? (
                        <BreadcrumbPage ref={currentRef} tabIndex={-1}>
                          {crumb.label}
                        </BreadcrumbPage>
                      ) : crumb.onSelect ? (
                        <BreadcrumbLink asChild>
                          <button
                            type="button"
                            title={crumb.label}
                            onClick={() => select(crumb)}
                          >
                            {crumb.label}
                          </button>
                        </BreadcrumbLink>
                      ) : (
                        // Not a link, so BreadcrumbLink's parent cap is set by hand.
                        <span
                          title={crumb.label}
                          className="max-w-[16ch] truncate"
                        >
                          {crumb.label}
                        </span>
                      )}
                    </BreadcrumbItem>
                  </Fragment>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
          {badge ? <span className="flex shrink-0">{badge}</span> : null}
        </div>
        {actions ? (
          <div className="flex w-full flex-row flex-nowrap items-center justify-end gap-2 sm:w-auto">
            {actions}
          </div>
        ) : null}
      </div>
      {byline ? (
        <p className="text-muted-foreground text-sm">{byline}</p>
      ) : null}
    </div>
  );
}
