import * as React from 'react';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

type FormFieldControl = {
  id: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
  disabled: boolean;
};

const FormFieldContext = React.createContext<FormFieldControl | null>(null);

type ControlProps = {
  id?: string;
  disabled?: boolean;
  'aria-invalid'?: React.AriaAttributes['aria-invalid'];
  'aria-describedby'?: string;
  'aria-required'?: React.AriaAttributes['aria-required'];
};

/**
 * Fills a field's id, disabled and aria wiring from the FormField around it.
 * Props the caller passed win; outside a FormField the props come back as-is.
 * Input, Textarea, SelectTrigger and Checkbox call it, so any of them works
 * as a FormField child, even nested (a SelectTrigger inside a Select).
 */
function useFormFieldControl<T extends ControlProps>(props: T): T {
  const field = React.useContext(FormFieldContext);
  if (!field) return props;
  return {
    ...props,
    id: props.id ?? field.id,
    disabled: props.disabled ?? (field.disabled || undefined),
    'aria-invalid': props['aria-invalid'] ?? (field.invalid || undefined),
    'aria-describedby': props['aria-describedby'] ?? field.describedBy,
    'aria-required': props['aria-required'] ?? (field.required || undefined),
  };
}

type FormFieldProps = {
  label: React.ReactNode;
  /** Draws the red star and sets aria-required (not native `required`). */
  required?: boolean;
  /** A muted line under the field. */
  hint?: React.ReactNode;
  /** A red line under the hint (role="alert"); also marks the field invalid. */
  error?: React.ReactNode;
  /** Dims the label and disables the field. */
  disabled?: boolean;
  /** The field's id; generated when neither this nor the field sets one. */
  id?: string;
  /** Layout only (width, margin, grid placement). */
  className?: string;
  children: React.ReactNode;
};

/**
 * A labelled form field: Label, the field, an optional hint and error, 6px
 * apart. Wires `htmlFor`, `aria-invalid`, `aria-describedby` and
 * `aria-required` to the field through context (see useFormFieldControl).
 */
function FormField({
  label,
  required = false,
  hint,
  error,
  disabled = false,
  id,
  className,
  children,
}: FormFieldProps) {
  const generatedId = React.useId();
  const childId = React.isValidElement<{ id?: string }>(children)
    ? children.props.id
    : undefined;
  const fieldId = id ?? childId ?? generatedId;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;

  const control = React.useMemo<FormFieldControl>(
    () => ({
      id: fieldId,
      describedBy,
      invalid: Boolean(error),
      required,
      disabled,
    }),
    [fieldId, describedBy, error, required, disabled],
  );

  return (
    <div
      data-slot="form-field"
      data-disabled={disabled || undefined}
      className={cn('group flex flex-col gap-1.5', className)}
    >
      <Label htmlFor={fieldId} className="gap-1">
        {label}
        {required ? (
          <span aria-hidden="true" className="text-destructive">
            *
          </span>
        ) : null}
      </Label>
      <FormFieldContext.Provider value={control}>
        {children}
      </FormFieldContext.Provider>
      {hint ? (
        <p id={hintId} className="text-muted-foreground text-xs">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-destructive text-xs">
          {error}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Stops a FormField's wiring from reaching fields rendered inside this
 * subtree (a popover's search box), which would otherwise share its id.
 */
function FormFieldBoundary({ children }: { children: React.ReactNode }) {
  return (
    <FormFieldContext.Provider value={null}>
      {children}
    </FormFieldContext.Provider>
  );
}

export { FormField, FormFieldBoundary, useFormFieldControl };
export type { FormFieldProps };
