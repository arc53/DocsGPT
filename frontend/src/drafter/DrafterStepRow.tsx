import { ChevronDown, type LucideIcon } from 'lucide-react';
import { type ReactNode, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { Collapsible } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';

/**
 * A step row in the drafter's conversation, the chat's step-row recipe
 * (PATTERNS.md › Chat answer column): a muted 16px icon, muted 14px text and
 * a chevron on a `ghost sm` button that opens its rows, a list of rows
 * (28px at least, wrapping) on a 1px rule (StepGroup's shape). The rows are
 * the children, usually FilledRows. With no children it is a plain line with
 * nothing to open. "Filled 2 fields" under a proposal, and each finished
 * step of a guided build folded to its result.
 *
 * Args:
 *   icon: The row's lucide icon (ListChecks, CircleCheck).
 *   label: What the step did ("Filled 2 fields", "Basics: Shipping help").
 *   children: The rows it opens.
 *   defaultOpen: Start open.
 *   undone: How many of its fields the user undid since; above zero the
 *     label adds "· 1 undone".
 */
export function DrafterStepRow({
  icon: Icon,
  label: stepLabel,
  children,
  defaultOpen = false,
  undone = 0,
}: {
  icon: LucideIcon;
  label: string;
  children?: ReactNode;
  defaultOpen?: boolean;
  undone?: number;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const label =
    undone > 0
      ? `${stepLabel} · ${t('drafter.undone.count', { count: undone })}`
      : stepLabel;

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
          {/* Each FilledRow draws the rule from its icon to the next one's,
              so a row that wraps never runs it past the last icon. */}
          <div data-slot="drafter-step-rows" className="flex min-w-0 flex-col">
            {children}
          </div>
        </div>
      </Collapsible>
    </div>
  );
}

/** How a field the user undid stands: empty again, or back to what it held. */
export type UndoneKind = 'empty' | 'previous';

/**
 * One row in a DrafterStepRow: its icon on the rule (a dot when it has
 * none), then "<label> · <value>", or the value alone (an example question
 * it read). 28px for one line, and it wraps, so touch and keyboard users
 * read all of it. A field the user undid is muted and says so in place of
 * the value.
 *
 * Args:
 *   label: The field or step ("Name", "Knowledge and tools"); left out, the
 *     row is its value alone.
 *   value: What it now holds.
 *   icon: A lucide icon for the row; a dot stands in without one.
 *   undone: The user undid the field: "Undone, back to empty" or "Undone,
 *     back to the previous value".
 */
export function FilledRow({
  label,
  value,
  icon: Icon,
  undone,
}: {
  label?: string;
  value: string;
  icon?: LucideIcon;
  undone?: UndoneKind;
}) {
  const { t } = useTranslation();
  const text = undone ? t(`drafter.undone.${undone}`) : value;
  return (
    <div
      data-slot="filled-row"
      className={cn(
        'relative flex min-h-7 min-w-0 items-start gap-2 py-1 text-sm',
        // In a step row's list, the rule from this icon's centre (top-3.5)
        // down to the next one's.
        'in-data-[slot=drafter-step-rows]:not-last:before:bg-border in-data-[slot=drafter-step-rows]:not-last:before:absolute in-data-[slot=drafter-step-rows]:not-last:before:top-3.5 in-data-[slot=drafter-step-rows]:not-last:before:-bottom-3.5 in-data-[slot=drafter-step-rows]:not-last:before:left-2 in-data-[slot=drafter-step-rows]:not-last:before:w-px',
        undone && 'text-muted-foreground',
      )}
    >
      {/* The background masks the rule behind the icon; mt-0.5 centres it
          on the first line. */}
      <span className="bg-background relative mt-0.5 flex size-4 shrink-0 items-center justify-center">
        {Icon ? (
          <Icon className="text-muted-foreground size-4" aria-hidden="true" />
        ) : (
          <span className="bg-muted-foreground/50 size-1.5 rounded-full" />
        )}
      </span>
      <p className="min-w-0 wrap-break-word">
        {label && (
          <>
            <span className="font-medium">{label}</span> ·{' '}
          </>
        )}
        {text}
      </p>
    </div>
  );
}
