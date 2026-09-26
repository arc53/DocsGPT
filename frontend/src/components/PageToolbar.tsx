import type { ReactNode } from 'react';

import { Separator } from './ui/separator';

/**
 * The block under a section page's title: an intro line, then a row with the
 * page search on the left and the page action (an Add pill) on the right,
 * optionally closed by a rule. Notices that belong to the action (a limit
 * warning) go in `children`, under the row.
 */
export default function PageToolbar({
  intro,
  search,
  action,
  divider = false,
  children,
}: {
  intro?: ReactNode;
  search?: ReactNode;
  action?: ReactNode;
  divider?: boolean;
  children?: ReactNode;
}) {
  // With no search, the intro takes the row's left slot beside the action.
  const introInRow = !search && intro;

  return (
    <div data-slot="page-toolbar">
      {intro && !introInRow ? (
        <p className="text-muted-foreground mb-5 text-sm leading-6">{intro}</p>
      ) : null}
      <div className="mb-6 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        {introInRow ? (
          <p className="text-muted-foreground max-w-2xl text-sm leading-6">
            {intro}
          </p>
        ) : search ? (
          <div className="w-full max-w-md">{search}</div>
        ) : null}
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      {children}
      {divider ? <Separator className="mb-8" /> : null}
    </div>
  );
}
