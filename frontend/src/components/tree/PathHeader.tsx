import type { ReactNode } from 'react';
import { ArrowLeft } from 'lucide-react';
import { Fragment } from 'react';

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '../ui/breadcrumb';
import { IconButton } from '../ui/icon-button';

type Crumb = { label: string; onSelect?: () => void };

/**
 * The path row above a source's file tree and chunk viewer: a back button,
 * the source and folder crumbs, and actions (search, sync, edit) on the
 * right. The last crumb is the current one and truncates.
 */
export default function PathHeader({
  root,
  segments = [],
  onBack,
  backLabel,
  actions,
}: {
  root: Crumb;
  segments?: Crumb[];
  onBack: () => void;
  backLabel: string;
  actions?: ReactNode;
}) {
  const crumbs = [root, ...segments];

  return (
    <div className="flex min-h-9.5 flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex w-full min-w-0 items-center sm:w-auto">
        <IconButton
          variant="outline"
          size="icon-xs"
          shape="pill"
          className="mr-3"
          label={backLabel}
          icon={ArrowLeft}
          side="bottom"
          onClick={onBack}
        />
        <Breadcrumb className="min-w-0">
          <BreadcrumbList>
            {crumbs.map((crumb, index) => {
              const isLast = index === crumbs.length - 1;
              return (
                <Fragment key={`${index}-${crumb.label}`}>
                  {index > 0 ? <BreadcrumbSeparator /> : null}
                  <BreadcrumbItem>
                    {isLast ? (
                      <BreadcrumbPage
                        className="max-w-[32ch]"
                        title={crumb.label}
                      >
                        {crumb.label}
                      </BreadcrumbPage>
                    ) : crumb.onSelect ? (
                      <BreadcrumbLink asChild>
                        <button type="button" onClick={crumb.onSelect}>
                          {crumb.label}
                        </button>
                      </BreadcrumbLink>
                    ) : (
                      <span>{crumb.label}</span>
                    )}
                  </BreadcrumbItem>
                </Fragment>
              );
            })}
          </BreadcrumbList>
        </Breadcrumb>
      </div>
      {actions ? (
        <div className="relative flex w-full flex-row flex-nowrap items-center justify-end gap-2 sm:w-auto">
          {actions}
        </div>
      ) : null}
    </div>
  );
}
