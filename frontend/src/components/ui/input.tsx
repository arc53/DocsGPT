import * as React from 'react';

import { cn } from '@/lib/utils';

type InputProps = React.ComponentProps<'input'> & {
  label?: React.ReactNode;
  leftIcon?: React.ReactNode;
  labelBgClassName?: string;
};

const baseInputClasses =
  'text-foreground file:text-foreground placeholder:text-muted-foreground border-border h-[42px] w-full min-w-0 rounded-md border bg-transparent px-3 py-2 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm';

const themeInputClasses =
  'dark:border-border dark:text-white dark:placeholder:text-gray-400 selection:bg-primary selection:text-primary-foreground focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive';

function Input({
  className,
  type,
  label,
  leftIcon,
  labelBgClassName = 'bg-card',
  id,
  placeholder,
  required,
  ...props
}: InputProps) {
  const generatedId = React.useId();
  const inputId = id ?? (label ? generatedId : undefined);

  if (!label) {
    return (
      <input
        type={type}
        id={id}
        placeholder={placeholder}
        required={required}
        data-slot="input"
        className={cn(baseInputClasses, themeInputClasses, className)}
        {...props}
      />
    );
  }

  return (
    <div className="relative">
      <input
        type={type}
        id={inputId}
        data-slot="input"
        // Use a single-space placeholder so :placeholder-shown drives the
        // floating-label peer-trick even when the caller didn't pass one.
        placeholder={placeholder ?? ' '}
        required={required}
        className={cn(
          baseInputClasses,
          themeInputClasses,
          'peer placeholder:text-transparent dark:placeholder:text-transparent',
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
          'text-muted-foreground pointer-events-none absolute -top-2.5 left-3 max-w-[calc(100%-24px)] cursor-none overflow-hidden px-2 text-xs text-ellipsis whitespace-nowrap transition-all select-none',
          'peer-placeholder-shown:top-2.5 peer-placeholder-shown:text-base',
          leftIcon
            ? 'peer-placeholder-shown:left-7'
            : 'peer-placeholder-shown:left-3',
          'peer-focus:-top-2.5 peer-focus:left-3 peer-focus:text-xs',
          labelBgClassName,
        )}
      >
        {label}
        {required ? <span className="text-destructive ml-0.5">*</span> : null}
      </label>
    </div>
  );
}

export { Input };
export type { InputProps };
