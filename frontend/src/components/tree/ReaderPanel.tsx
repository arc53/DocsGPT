import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { Card } from '../ui/card';
import { Separator } from '../ui/separator';

/**
 * The reader of a source view: the content you read and edit (a wiki page,
 * an open chunk) in a `subtle` panel, a place per DESIGN.md's Card surfaces.
 * Its meta sits left and its actions right in the panel's own header row, so
 * Edit, then Cancel and Save, stay beside the text they act on.
 */
export default function ReaderPanel({
  meta,
  actions,
  children,
  className,
}: {
  /** Muted 12px lines (provenance, token count, path). */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** Layout only. */
  className?: string;
}) {
  return (
    <Card
      variant="subtle"
      padding="none"
      className={cn('min-w-0 gap-0', className)}
    >
      <div className="flex min-h-14 flex-wrap items-center justify-between gap-3 px-6 py-3">
        <div className="text-muted-foreground flex min-w-0 flex-col text-xs">
          {meta}
        </div>
        {actions ? (
          <div className="flex items-center gap-2">{actions}</div>
        ) : null}
      </div>
      <Separator />
      <div className="min-w-0 px-6 py-5">{children}</div>
    </Card>
  );
}
