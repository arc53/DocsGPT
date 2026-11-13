import type { ReactNode } from 'react';

import { Separator } from './ui/separator';

/**
 * The block under a section page's title: an intro line, then a row with the
 * page search on the left and the page action (an Add pill) on the right,
 * optionally closed by a rule. Notices that belong to the action (a limit
 * warning) go in `children`, under the row. `stack={false}` keeps a small
 * action (a lone ⋯) beside the intro on a phone instead of under it, the
 * row still at the 38px field height.
 */
export default function PageToolbar({
  intro,
  search,
  action,
  divider = false,
  stack = true,
  children,
}: {
  intro?: ReactNode;
  search?: ReactNode;
  action?: ReactNode;
  divider?: boolean;
  stack?: boolean;
  children?: ReactNode;
}) {
  // With no search, the intro takes the row's left slot beside the action.
  const introInRow = !search && intro;

  return (
    // A container: the row stacks by its own width, so it also stacks when a
    // docked side panel narrows the page on a wide screen.
    <div data-slot="page-toolbar" className="@container">
      {intro && !introInRow ? (
        <p className="text-muted-foreground mb-5 text-sm leading-6">{intro}</p>
      ) : null}
      <div
        className={
          stack
            ? 'mb-6 flex flex-col items-start gap-3 @2xl:flex-row @2xl:items-center @2xl:justify-between'
            : 'mb-6 flex min-h-9.5 items-center justify-between gap-3'
        }
      >
        {introInRow ? (
          <p className="text-muted-foreground max-w-2xl text-sm leading-6">
            {intro}
          </p>
        ) : search ? (
          <div className="w-full max-w-md">{search}</div>
        ) : null}
        {/* Spans the stacked row on a narrow page, so a caller can stretch
            its main button; hugs its buttons once the row fits. */}
        {action ? (
          <div className={stack ? 'w-full shrink-0 @2xl:w-auto' : 'shrink-0'}>
            {action}
          </div>
        ) : null}
      </div>
      {children}
      {divider ? <Separator className="mb-8" /> : null}
    </div>
  );
}
