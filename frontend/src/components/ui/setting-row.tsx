import * as React from 'react';

import { FormFieldControlProvider } from '@/components/ui/form-field';
import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

/** A group of SettingRows, split by faint dividers. Layout classes only. */
function SettingRows({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="setting-rows"
      className={cn('divide-border/50 divide-y', className)}
      {...props}
    />
  );
}

type SettingRowProps = {
  label: React.ReactNode;
  description?: React.ReactNode;
  /**
   * The control's id, so clicking the label toggles it and names it.
   * Generated when omitted; a ui/ control (Switch, Input, SelectTrigger…)
   * takes it from the row, so it needs no `id` of its own.
   */
  htmlFor?: string;
  /** Top-align the control, for descriptions that wrap. */
  alignStart?: boolean;
  /**
   * Put the control under the title below `sm` and let it take the row's
   * width, for controls too wide to share a phone row (a picker).
   */
  stack?: boolean;
  /**
   * The title element. `label` (default) names the control; a heading tag
   * keeps the document outline, and the control then needs its own
   * aria-label.
   */
  as?: 'label' | 'h2' | 'h3';
  /** A field under the row that belongs to it (a limit Input under a Switch). */
  after?: React.ReactNode;
  /** Layout only. */
  className?: string;
  /** The control on the right: a Switch, a small Input, a Select. */
  children?: React.ReactNode;
};

/**
 * A settings row: title and muted description on the left, a control on the
 * right, 12px of padding above and below (none at the ends of its group).
 * Like FormField it wires the control through context: the control gets the
 * row's id (`htmlFor`, or a generated one) and `aria-describedby` pointing at
 * the description. The `after` field is not wired.
 */
function SettingRow({
  label,
  description,
  htmlFor,
  alignStart = false,
  stack = false,
  as = 'label',
  after,
  className,
  children,
}: SettingRowProps) {
  const Heading = as === 'label' ? null : as;
  const generatedId = React.useId();
  const controlId = htmlFor ?? generatedId;
  // Its own id, not one derived from the control's: a `[id^=…]` lookup for
  // the control must not land on the description.
  const generatedDescriptionId = React.useId();
  const descriptionId = description ? generatedDescriptionId : undefined;
  return (
    <div
      data-slot="setting-row"
      className={cn('py-3 first:pt-0 last:pb-0', className)}
    >
      <div
        className={cn(
          'flex justify-between gap-4',
          stack
            ? cn(
                'flex-col gap-y-2 sm:flex-row',
                alignStart ? 'sm:items-start' : 'sm:items-center',
              )
            : cn('flex-row', alignStart ? 'items-start' : 'items-center'),
        )}
      >
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {Heading ? (
            <Heading className="text-foreground text-sm leading-none font-medium">
              {label}
            </Heading>
          ) : (
            <Label
              htmlFor={controlId}
              className="text-foreground w-fit text-sm font-medium"
            >
              {label}
            </Label>
          )}
          {description ? (
            <p id={descriptionId} className="text-muted-foreground text-xs">
              {description}
            </p>
          ) : null}
        </div>
        {children ? (
          <div className={cn('shrink-0', stack && 'w-full sm:w-auto')}>
            <FormFieldControlProvider
              id={controlId}
              describedBy={descriptionId}
            >
              {children}
            </FormFieldControlProvider>
          </div>
        ) : null}
      </div>
      {after ? <div className="mt-2">{after}</div> : null}
    </div>
  );
}

export { SettingRow, SettingRows };
export type { SettingRowProps };
