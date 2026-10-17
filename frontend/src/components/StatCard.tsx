import * as React from 'react';

import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

const VALUE_TONES = {
  destructive: 'text-destructive',
  warning: 'text-warning',
  info: 'text-info',
  muted: 'text-muted-foreground',
} as const;

type StatCardProps = Omit<React.ComponentProps<'div'>, 'title' | 'children'> & {
  /** Muted caption above the figure. */
  label: React.ReactNode;
  /** The figure itself, set large in tabular numerals. */
  value: React.ReactNode;
  /** Optional 12px muted line under the figure. */
  sub?: React.ReactNode;
  /** Native tooltip on the tile; adds a help cursor. */
  hint?: string;
  /** Card surface: `subtle` on a page, `outline` inside a modal (bg-card). */
  variant?: 'subtle' | 'outline';
  /** `destructive` gives the tile the danger soft fill and border. */
  tone?: 'default' | 'destructive';
  /** Colours the figure by meaning; omitted, it inherits the card foreground. */
  valueTone?: keyof typeof VALUE_TONES;
  /** Shows a figure-sized Skeleton in place of the value. */
  loading?: boolean;
};

/**
 * A stat tile: label, big tabular figure and an optional sub line on a
 * Card. `className` is for layout only (grid placement, width).
 */
function StatCard({
  label,
  value,
  sub,
  hint,
  variant = 'subtle',
  tone = 'default',
  valueTone,
  loading = false,
  className,
  ...rest
}: StatCardProps) {
  return (
    <Card
      variant={variant}
      tone={tone}
      padding="lg"
      title={hint}
      className={cn('gap-1', hint && 'cursor-help', className)}
      {...rest}
    >
      <p className="text-muted-foreground text-sm">{label}</p>
      {loading ? (
        <Skeleton className="h-8 w-12" />
      ) : (
        <p
          className={cn(
            'text-2xl font-bold tabular-nums',
            valueTone && VALUE_TONES[valueTone],
          )}
        >
          {value}
        </p>
      )}
      {sub ? <p className="text-muted-foreground text-xs">{sub}</p> : null}
    </Card>
  );
}

export default StatCard;
export { StatCard };
export type { StatCardProps };
