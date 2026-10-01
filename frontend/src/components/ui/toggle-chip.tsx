import * as React from 'react';
import { Lock } from 'lucide-react';
import { Toggle as TogglePrimitive } from 'radix-ui';

import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type ToggleChipSize = 'xs' | 'sm';

/**
 * xs pills get 10px sides (the rectangular xs is 8px), the widening the
 * default/field/lg pills get from Button; sm pills keep Button's 12px.
 */
const pillPadding: Record<ToggleChipSize, string> = {
  xs: 'px-2.5 has-[>svg,>[data-slot=button-label]>svg]:px-2.5',
  sm: '',
};

/**
 * A pressed-chip toggle for "any of N" choices that wrap in a row (guardrail
 * stages, PII entities, model capabilities, a code view): the tint means on
 * (`secondary`), off is `ghost-muted`, both pills. Radix Toggle gives it
 * `aria-pressed` and `data-state`. Use ToggleGroup for a segmented "one of N"
 * control instead.
 *
 * A `locked` chip is on and can't be turned off (an instance-enforced
 * control): it keeps full colour and a trailing Lock, and is `aria-disabled`
 * rather than `disabled`, so it stays readable and its `title` still shows on
 * hover; clicks don't toggle it. `disabled` is for a chip that is genuinely
 * unavailable (a view-only form) and fades it like any disabled button.
 *
 * Args:
 *   pressed: Whether the chip is on.
 *   onPressedChange: Called with the next state when clicked (never while locked).
 *   size: `xs` (28px, default) for dense panels, `sm` (32px) in forms.
 *   locked: Hold the chip on with a Lock and ignore clicks.
 */
function ToggleChip({
  className,
  size = 'xs',
  pressed,
  locked = false,
  onPressedChange,
  children,
  ...props
}: Omit<
  React.ComponentProps<typeof TogglePrimitive.Root>,
  'defaultPressed' | 'asChild'
> & {
  pressed: boolean;
  size?: ToggleChipSize;
  locked?: boolean;
}) {
  const on = pressed || locked;
  const variant = on ? 'secondary' : 'ghost-muted';
  return (
    <TogglePrimitive.Root
      type="button"
      data-slot="toggle-chip"
      data-variant={variant}
      data-size={size}
      data-shape="pill"
      data-locked={locked ? '' : undefined}
      pressed={on}
      onPressedChange={locked ? undefined : onPressedChange}
      aria-disabled={locked || undefined}
      className={cn(
        buttonVariants({ variant, size, shape: 'pill' }),
        pillPadding[size],
        locked && 'hover:bg-secondary cursor-default',
        className,
      )}
      {...props}
    >
      {children}
      {locked && <Lock aria-hidden="true" className="size-3" />}
    </TogglePrimitive.Root>
  );
}

export { ToggleChip };
