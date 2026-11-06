import { ChevronDown, type LucideIcon } from 'lucide-react';
import { type ReactNode, useId, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Collapsible } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';

/**
 * A step row in the drafter's conversation, the chat's step-row recipe
 * (PATTERNS.md › Chat answer column): a muted 16px icon, muted 14px text and
 * a chevron on a `ghost sm` button that opens its rows, a list of 28px
 * one-line rows on a 1px rule (StepGroup's shape). The rows are the
 * children, usually FilledRows. With no children it is a plain line with
 * nothing to open. "Filled 2 fields" under a proposal, and each finished
 * step of a guided build folded to its result.
 *
 * Args:
 *   icon: The row's lucide icon (ListChecks, CircleCheck).
 *   label: What the step did ("Filled 2 fields", "Basics: Shipping help").
 *   children: The rows it opens.
 *   defaultOpen: Start open.
 */
export function DrafterStepRow({
  icon: Icon,
  label,
  children,
  defaultOpen = false,
}: {
  icon: LucideIcon;
  label: string;
  children?: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  if (!children) {
    return (
      <p
        data-slot="drafter-step-row"
        className="text-muted-foreground flex min-h-8 min-w-0 items-center gap-1.5 text-sm font-medium"
      >
        <Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="min-w-0 truncate">{label}</span>
      </p>
    );
  }

  return (
    <div data-slot="drafter-step-row" className="flex min-w-0 flex-col">
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => setOpen(!open)}
        // size sm's has-[>svg]:px-2.5, pulled back so the icon sits on the
        // conversation's text column.
        className="-ml-2.5 w-fit max-w-full justify-start"
      >
        <Icon className="text-muted-foreground" aria-hidden="true" />
        <span className="text-muted-foreground min-w-0 truncate">{label}</span>
        <ChevronDown
          aria-hidden="true"
          className={cn(
            'text-muted-foreground shrink-0 transition-transform duration-200 motion-reduce:transition-none',
            open && 'rotate-180',
          )}
        />
      </Button>
      <Collapsible id={bodyId} open={open}>
        <div className="pt-1">
          <div className="relative flex min-w-0 flex-col">
            {/* The rule runs through the icon centres (left-2 of a 16px
                icon). */}
            <span
              aria-hidden="true"
              className="bg-border absolute top-3.5 bottom-3.5 left-2 w-px"
            />
            {children}
          </div>
        </div>
      </Collapsible>
    </div>
  );
}

/**
 * One 28px row in a DrafterStepRow: its icon on the rule (a dot when it has
 * none), then "<label> · <value>" on one line, cut with the whole line as
 * its title.
 *
 * Args:
 *   label: The field or step ("Name", "Knowledge and tools").
 *   value: What it now holds.
 *   icon: A lucide icon for the row; a dot stands in without one.
 */
export function FilledRow({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon?: LucideIcon;
}) {
  return (
    <div
      data-slot="filled-row"
      className="flex h-7 min-w-0 items-center gap-2 text-sm"
    >
      {/* The background masks the rule behind the icon. */}
      <span className="bg-background relative flex size-4 shrink-0 items-center justify-center">
        {Icon ? (
          <Icon className="text-muted-foreground size-4" aria-hidden="true" />
        ) : (
          <span className="bg-muted-foreground/50 size-1.5 rounded-full" />
        )}
      </span>
      <p className="min-w-0 truncate" title={`${label} · ${value}`}>
        <span className="font-medium">{label}</span> · {value}
      </p>
    </div>
  );
}
