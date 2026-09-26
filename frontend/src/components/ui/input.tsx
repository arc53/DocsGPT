import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import {
  useFormFieldControl,
  useFormFieldFloating,
} from '@/components/ui/form-field';
import { cn, focusRing, invalidState, fieldFrame } from '@/lib/utils';

const inputVariants = cva(
  `${focusRing} ${invalidState} ${fieldFrame} text-foreground file:text-foreground placeholder:text-muted-foreground w-full min-w-0 bg-transparent file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:cursor-not-allowed disabled:opacity-50 selection:bg-primary selection:text-primary-foreground focus-visible:border-ring`,
  {
    variants: {
      size: {
        default: 'h-9.5 px-3 py-1.5 text-base md:text-sm',
        sm: 'h-8 px-2 py-1 text-sm',
        lg: 'h-12 px-5 py-3 text-base md:text-sm',
        // The form-row height (38px) by name, shared with Button field and
        // SelectTrigger field; the same classes as default.
        field: 'h-9.5 px-3 py-1.5 text-base md:text-sm',
      },
      shape: {
        default: 'rounded-md',
        pill: 'rounded-full',
      },
      // Declared after size and shape so cn() lets it win over them.
      variant: {
        default: '',
        // A field inside a host that already draws the frame (a renaming
        // sidebar row, a search strip in a bordered panel): no border,
        // padding, radius, shadow or ring of its own.
        bare: 'h-auto rounded-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0',
        // A field on a muted panel: keeps the card fill so it still reads
        // as a field against the panel.
        filled: 'bg-card',
      },
    },
    compoundVariants: [
      // A default-size pill would start its text 12px from a 21px round end;
      // pad it like the lg pill and SelectTrigger's pills (text 21px in).
      // Not on `bare`, which has no padding of its own.
      {
        shape: 'pill',
        size: ['default', 'field'],
        variant: ['default', 'filled'],
        class: 'px-5',
      },
    ],
    defaultVariants: {
      size: 'default',
      shape: 'default',
      variant: 'default',
    },
  },
);

// Where the floating label sits while the field is empty, per input height.
const LABEL_RESTING_CLASSES: Record<
  NonNullable<VariantProps<typeof inputVariants>['size']>,
  string
> = {
  default: 'peer-placeholder-shown:top-2 peer-placeholder-shown:text-base',
  sm: 'peer-placeholder-shown:top-1.5 peer-placeholder-shown:text-sm',
  lg: 'peer-placeholder-shown:top-3.5 peer-placeholder-shown:text-base',
  field: 'peer-placeholder-shown:top-2 peer-placeholder-shown:text-base',
};

// The floating label sits on the field's border, so its background has to
// match whatever surface the field is placed on to hide the line behind it.
const LABEL_SURFACE_CLASSES = {
  card: 'bg-card',
  background: 'bg-background',
  muted: 'bg-muted',
} as const;

type InputProps = Omit<React.ComponentProps<'input'>, 'size'> &
  VariantProps<typeof inputVariants> & {
    label?: React.ReactNode;
    leftIcon?: React.ReactNode;
    /** Surface behind the field, so the floating label's notch blends in. */
    labelSurface?: keyof typeof LABEL_SURFACE_CLASSES;
  };

function Input(inputProps: InputProps) {
  const {
    className,
    type,
    label,
    leftIcon,
    labelSurface = 'card',
    id,
    placeholder,
    required,
    size = 'default',
    shape = 'default',
    variant = 'default',
    ...props
  } = useFormFieldControl(inputProps);
  const floating = useFormFieldFloating();
  const generatedId = React.useId();
  const inputId = id ?? (label ? generatedId : undefined);

  if (!label) {
    const field = (
      <input
        type={type}
        id={id}
        // Under a FormField's floating label a blank placeholder drives the
        // resting position; a real one stays hidden until focus.
        placeholder={placeholder ?? (floating ? ' ' : undefined)}
        required={required}
        data-slot="input"
        data-size={size}
        data-shape={shape}
        data-variant={variant}
        data-left-icon={leftIcon ? '' : undefined}
        className={cn(
          inputVariants({ size, shape, variant }),
          floating &&
            'focus:placeholder:text-muted-foreground placeholder:text-transparent',
          leftIcon && 'pl-10',
          className,
        )}
        {...props}
      />
    );
    if (!leftIcon) return field;
    // An inset icon with no floating label (a search field).
    return (
      <div className="relative">
        {field}
        <div className="pointer-events-none absolute top-1/2 left-3 flex -translate-y-1/2 items-center justify-center">
          {leftIcon}
        </div>
      </div>
    );
  }

  return (
    <div className="relative">
      <input
        type={type}
        id={inputId}
        data-slot="input"
        data-size={size}
        data-shape={shape}
        data-variant={variant}
        // Use a single-space placeholder so :placeholder-shown drives the
        // floating-label peer-trick even when the caller didn't pass one.
        placeholder={placeholder ?? ' '}
        required={required}
        className={cn(
          inputVariants({ size, shape, variant }),
          'peer focus:placeholder:text-muted-foreground placeholder:text-transparent',
          leftIcon && 'pl-10',
          className,
        )}
        {...props}
      />
      {leftIcon ? (
        <div className="pointer-events-none absolute top-1/2 left-3 flex -translate-y-1/2 items-center justify-center">
          {leftIcon}
        </div>
      ) : null}
      <label
        htmlFor={inputId}
        className={cn(
          'text-muted-foreground pointer-events-none absolute -top-2.5 left-3 max-w-[calc(100%-24px)] overflow-hidden px-2 text-xs text-ellipsis whitespace-nowrap transition-all select-none',
          LABEL_RESTING_CLASSES[size ?? 'default'],
          leftIcon
            ? 'peer-placeholder-shown:left-7'
            : 'peer-placeholder-shown:left-3',
          'peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs',
          LABEL_SURFACE_CLASSES[labelSurface],
        )}
      >
        {label}
        {required ? <span className="text-destructive ml-0.5">*</span> : null}
      </label>
    </div>
  );
}

export { Input, inputVariants };
export type { InputProps };
