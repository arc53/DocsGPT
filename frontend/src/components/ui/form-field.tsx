import * as React from 'react';

import { Label } from '@/components/ui/label';
import { cn } from '@/lib/utils';

type FormFieldControl = {
  id: string;
  describedBy?: string;
  invalid: boolean;
  required: boolean;
  disabled: boolean;
  /** The label floats on the field's border (see FormField `float`). */
  floating: boolean;
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
/**
 * True inside a FormField whose label floats on the field. Input and Textarea
 * use it to keep a placeholder hidden under the resting label until focus.
 */
function useFormFieldFloating(): boolean {
  return React.useContext(FormFieldContext)?.floating ?? false;
}

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
  /**
   * The label sits on the field's border (the default). Pass false for a
   * field with no single box to sit on (a list of checkboxes, several
   * controls in a row); the label then sits above it.
   */
  float?: boolean;
  /** Surface behind the field, so the floating label's notch blends in. */
  labelSurface?: keyof typeof LABEL_SURFACE_CLASSES;
  /** Layout only (width, margin, grid placement). */
  className?: string;
  children: React.ReactNode;
};

// The floating label sits on the border, so its background has to match the
// surface the field is placed on to hide the line behind it.
const LABEL_SURFACE_CLASSES = {
  card: 'bg-card',
  background: 'bg-background',
  muted: 'bg-muted',
} as const;

// Where the floating label rests while its Input or Textarea is empty and
// unfocused, per control size; every other control keeps it on the border.
// Only the field itself counts (up to two levels down, for an Input with an
// icon or a Textarea under an overlay), not a search box in an inline menu.
const FLOATING_LABEL_REST = [
  'group-has-[>input:placeholder-shown:not(:focus),>*>input:placeholder-shown:not(:focus)]/float:top-2 group-has-[>input:placeholder-shown:not(:focus),>*>input:placeholder-shown:not(:focus)]/float:text-base',
  'group-has-[>input[data-size=sm]:placeholder-shown:not(:focus)]/float:top-1.5 group-has-[>input[data-size=sm]:placeholder-shown:not(:focus)]/float:text-sm',
  'group-has-[>input[data-size=lg]:placeholder-shown:not(:focus)]/float:top-3.5',
  'group-has-[>*>input[data-left-icon]:placeholder-shown:not(:focus)]/float:left-7',
  'group-has-[>textarea:placeholder-shown:not(:focus),>*>textarea:placeholder-shown:not(:focus)]/float:top-2 group-has-[>textarea:placeholder-shown:not(:focus),>*>textarea:placeholder-shown:not(:focus)]/float:text-base',
  'group-has-[>textarea[data-size=lg]:placeholder-shown:not(:focus),>*>textarea[data-size=lg]:placeholder-shown:not(:focus)]/float:top-3',
].join(' ');

/**
 * A labelled form field: the field with its label floating on the border,
 * then an optional hint and error, 6px apart. The label rests inside an empty
 * Input or Textarea and moves up on focus; on a Select, combobox, MultiSelect
 * or Dropzone it stays on the border. Wires `htmlFor`, `aria-invalid`,
 * `aria-describedby` and `aria-required` to the field through context (see
 * useFormFieldControl). Stack floating fields with `gap-5` so each label
 * clears the field above.
 */
function FormField({
  label,
  required = false,
  hint,
  error,
  disabled = false,
  id,
  float = true,
  labelSurface = 'card',
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
      floating: float,
    }),
    [fieldId, describedBy, error, required, disabled, float],
  );

  const star = required ? (
    <span aria-hidden="true" className="text-destructive">
      *
    </span>
  ) : null;
  const provided = (
    <FormFieldContext.Provider value={control}>
      {children}
    </FormFieldContext.Provider>
  );

  return (
    <div
      data-slot="form-field"
      data-disabled={disabled || undefined}
      className={cn('group flex flex-col gap-1.5', className)}
    >
      {float ? (
        <div className="group/float relative">
          {provided}
          <label
            htmlFor={fieldId}
            data-slot="form-field-label"
            className={cn(
              'pointer-events-none absolute -top-2.5 left-3 z-10 block max-w-[calc(100%-24px)] truncate px-2 text-xs transition-all select-none group-data-[disabled=true]:opacity-50',
              error ? 'text-destructive' : 'text-muted-foreground',
              FLOATING_LABEL_REST,
              LABEL_SURFACE_CLASSES[labelSurface],
            )}
          >
            {label}
            {required ? (
              <span aria-hidden="true" className="text-destructive ml-0.5">
                *
              </span>
            ) : null}
          </label>
        </div>
      ) : (
        <>
          <Label htmlFor={fieldId} className="gap-1">
            {label}
            {star}
          </Label>
          {provided}
        </>
      )}
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

export {
  FormField,
  FormFieldBoundary,
  useFormFieldControl,
  useFormFieldFloating,
};
export type { FormFieldProps };
