import * as React from 'react';

import { Card, CardDescription, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

type OptionCardProps = Omit<
  React.ComponentProps<'button'>,
  'title' | 'children'
> & {
  /** Icon shown in the tinted square; sized by the component. */
  icon: React.ReactNode;
  title: React.ReactNode;
  /** Optional second line. The tile stays the same height without it. */
  description?: React.ReactNode;
  /**
   * Marks the current choice in a single-select picker. Pass it (true or
   * false) only in a picker: the tile then becomes a radio. Left out, the
   * tile is a plain button (it advances a step or navigates).
   */
  selected?: boolean;
};

/**
 * Picker tile: a whole-card button with an icon, a title and an optional
 * description. Used wherever the user chooses one of several ways to
 * proceed (agent type, source type). Title-only tiles are fine.
 */
function OptionCard({
  icon,
  title,
  description,
  selected,
  className,
  type = 'button',
  ...props
}: OptionCardProps) {
  return (
    <Card interactive selected={selected} asChild className={className}>
      <button
        type={type}
        role={props.role ?? (selected !== undefined ? 'radio' : undefined)}
        aria-checked={selected}
        data-slot="option-card"
        {...props}
      >
        <span className="flex items-center gap-4">
          <span
            data-slot="option-card-icon"
            className={cn(
              'bg-secondary text-secondary-foreground flex size-12 shrink-0 items-center justify-center rounded-xl transition-colors [&>svg]:size-6',
              selected && 'bg-primary text-primary-foreground',
            )}
          >
            {icon}
          </span>
          <span className="flex min-w-0 flex-col gap-1">
            <CardTitle className="text-base">{title}</CardTitle>
            {description ? (
              <CardDescription>{description}</CardDescription>
            ) : null}
          </span>
        </span>
      </button>
    </Card>
  );
}

export { OptionCard };
export type { OptionCardProps };
