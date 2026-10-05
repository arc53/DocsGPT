import { cva, type VariantProps } from 'class-variance-authority';
import { CheckIcon } from 'lucide-react';
import { Checkbox as CheckboxPrimitive } from 'radix-ui';
import * as React from 'react';

import { useFormFieldControl } from '@/components/ui/form-field';
import { cn, focusRing, invalidState } from '@/lib/utils';

const checkboxVariants = cva(
  `${focusRing} ${invalidState} peer border-input dark:bg-input/30 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground dark:data-[state=checked]:bg-primary data-[state=checked]:border-primary focus-visible:border-ring shrink-0 rounded-sm border shadow-xs transition-shadow outline-none disabled:cursor-not-allowed disabled:opacity-50`,
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

/** A themed checkbox (Radix), so it looks the same on every OS and theme. */
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
        className="grid place-content-center text-current transition-none"
      >
        {/* text-current: a parent that greys un-coloured svgs (CommandItem,
            SelectItem) must not grey the tick. */}
        <CheckIcon
          className={
            size === 'sm' ? 'size-3 text-current' : 'size-3.5 text-current'
          }
        />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}

export { Checkbox, checkboxVariants };
export type { CheckboxProps };
