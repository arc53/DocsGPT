import { cva, type VariantProps } from 'class-variance-authority';
import { CheckIcon, MinusIcon } from 'lucide-react';
import { Checkbox as CheckboxPrimitive } from 'radix-ui';
import * as React from 'react';

import { useFormFieldControl } from '@/components/ui/form-field';
import { cn, focusRing, invalidState } from '@/lib/utils';

const checkboxVariants = cva(
  `${focusRing} ${invalidState} peer border-input dark:bg-input/30 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground dark:data-[state=checked]:bg-primary data-[state=checked]:border-primary data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-primary-foreground dark:data-[state=indeterminate]:bg-primary data-[state=indeterminate]:border-primary focus-visible:border-ring shrink-0 rounded-sm border shadow-xs transition-shadow outline-none disabled:cursor-not-allowed disabled:opacity-50`,
  {
    variants: {
      size: {
        // 16px, for rows of options (token scopes, parsed spec actions).
        default: 'size-4',
        // 14px, for dense table cells (ToolConfig's "Filled by LLM").
        sm: 'size-3.5',
      },
    },
    defaultVariants: { size: 'default' },
  },
);

type CheckboxProps = React.ComponentProps<typeof CheckboxPrimitive.Root> &
  VariantProps<typeof checkboxVariants>;

/**
 * A themed checkbox (Radix), so it looks the same on every OS and theme.
 * `checked="indeterminate"` draws a minus on the filled box (a folder partly
 * picked).
 */
function Checkbox(checkboxProps: CheckboxProps) {
  const {
    className,
    size = 'default',
    ...props
  } = useFormFieldControl(checkboxProps);
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      data-size={size}
      className={cn(checkboxVariants({ size }), className)}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="group grid place-content-center text-current transition-none"
      >
        {/* Both glyphs are drawn and the indicator's own state hides one, so
            an uncontrolled box (defaultChecked, a form reset) is right too.
            text-current: a parent that greys un-coloured svgs (CommandItem,
            SelectItem) must not grey the tick. */}
        <MinusIcon
          className={cn(
            size === 'sm' ? 'size-3' : 'size-3.5',
            'text-current group-data-[state=checked]:hidden',
          )}
        />
        <CheckIcon
          className={cn(
            size === 'sm' ? 'size-3' : 'size-3.5',
            'text-current group-data-[state=indeterminate]:hidden',
          )}
        />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox, checkboxVariants };
export type { CheckboxProps };
