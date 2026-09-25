import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { useFormFieldControl } from '@/components/ui/form-field';
import { cn, focusRing, invalidState, fieldFrame } from '@/lib/utils';

const textareaVariants = cva(
  `${focusRing} ${invalidState} ${fieldFrame} text-foreground placeholder:text-muted-foreground border-border selection:bg-primary selection:text-primary-foreground focus-visible:border-ring flex w-full min-w-0 bg-transparent disabled:cursor-not-allowed disabled:opacity-50`,
  {
    variants: {
      size: {
        default: 'min-h-16 rounded-md px-3 py-2 text-base md:text-sm',
        sm: 'min-h-8 rounded-md px-2 py-1 text-sm',
        lg: 'min-h-24 rounded-2xl px-4 py-3 text-base md:text-sm',
      },
      resize: {
        none: 'resize-none',
        vertical: 'resize-y',
        both: 'resize',
      },
      // Declared after size so cn() lets it win.
      variant: {
        default: '',
        // A field on a muted panel: keeps the card fill so it still reads
        // as a field against the panel (the same as Input's `filled`).
        filled: 'bg-card',
      },
    },
    defaultVariants: {
      size: 'default',
      resize: 'vertical',
      variant: 'default',
    },
  },
);

type TextareaProps = React.ComponentProps<'textarea'> &
  VariantProps<typeof textareaVariants>;

/** Multi-line sibling of Input; shares its border, ring and error styling. */
function Textarea(textareaProps: TextareaProps) {
  const {
    className,
    size = 'default',
    resize = 'vertical',
    variant = 'default',
    ...props
  } = useFormFieldControl(textareaProps);
  return (
    <textarea
      data-slot="textarea"
      data-size={size}
      data-variant={variant}
      className={cn(textareaVariants({ size, resize, variant }), className)}
      {...props}
    />
  );
}

export { Textarea, textareaVariants };
export type { TextareaProps };
