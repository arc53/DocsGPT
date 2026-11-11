import { Undo2 } from 'lucide-react';
import { useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';
import { SettingRow, type SettingRowProps } from '@/components/ui/setting-row';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { cn, focusRing } from '@/lib/utils';

/**
 * The "Drafted" chip on a field the drafter filled, with its undo button: a
 * brand Badge on a background pad, so it can sit on a field's border and
 * hide the line behind it like a floating label does.
 *
 * Args:
 *   onUndo: Puts the field's previous value back.
 *   fieldLabel: The field's name, for the undo button's accessible name.
 *   undoDisabled: The field can't change now (a draft is running).
 *   className: Layout only (placement on the field).
 */
export function DraftedBadge({
  onUndo,
  fieldLabel,
  undoDisabled = false,
  className,
}: {
  onUndo: () => void;
  fieldLabel: string;
  undoDisabled?: boolean;
  className?: string;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLSpanElement>(null);
  const label = t('drafter.undoField', {
    field: fieldLabel,
    interpolation: { escapeValue: false },
  });
  return (
    <span
      ref={ref}
      data-slot="drafted-badge"
      className={cn('bg-background inline-flex rounded-full', className)}
    >
      <Badge variant="default">
        {t('drafter.drafted')}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={label}
              onClick={() => {
                // The badge goes away with the undo: move focus first to the
                // control it restored, or it drops to <body>.
                if (ref.current) restoredControl(ref.current)?.focus();
                onUndo();
              }}
              disabled={undoDisabled}
              className={cn(
                focusRing,
                'hover:bg-background relative inline-flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-full outline-none after:absolute after:-inset-1 disabled:pointer-events-none disabled:opacity-50',
              )}
            >
              <Undo2 className="size-3" aria-hidden="true" />
            </button>
          </TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
      </Badge>
    </span>
  );
}

const FOCUSABLE =
  'input:not([type=hidden]):not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled), [tabindex]:not([tabindex="-1"])';

/**
 * The control a badge's undo restored: the first focusable one in its
 * DraftedField or SettingRow, else beside the badge, never the badge's own.
 */
function restoredControl(badge: HTMLElement): HTMLElement | null {
  const scope =
    badge.closest<HTMLElement>(
      '[data-slot=drafted-field], [data-slot=setting-row]',
    ) ?? badge.parentElement;
  if (!scope) return null;
  return (
    Array.from(scope.querySelectorAll<HTMLElement>(FOCUSABLE)).find(
      (el) => !badge.contains(el),
    ) ?? null
  );
}

// The drafted outline: the field's own frame in the brand colour and its
// floating label in the link colour, the way aria-invalid turns them red.
const DRAFTED_FRAME =
  '[&_[data-slot=input]]:border-primary [&_[data-slot=textarea]]:border-primary [&_[data-slot=select-trigger]]:border-primary [&_[data-slot=combobox-trigger]]:border-primary [&_[data-variant=combobox]]:border-primary [&_[data-slot=form-field-label]]:text-link';

/**
 * Wraps a form field the drafter may fill: while `drafted`, the field gets
 * the primary outline and a DraftedBadge on its top border, at the right,
 * where it shows whether or not the floating label rests inside the field.
 *
 * Args:
 *   drafted: Whether the field holds a drafted value.
 *   onUndo: Undo for the badge.
 *   fieldLabel: The field's name, for the undo button.
 *   undoDisabled: The badge's undo is off (a draft is running).
 *   className: Layout only (grid placement).
 *   children: The FormField (or a group of fields).
 */
export function DraftedField({
  drafted,
  onUndo,
  fieldLabel,
  undoDisabled,
  className,
  children,
}: {
  drafted: boolean;
  onUndo: () => void;
  fieldLabel: string;
  undoDisabled?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-slot="drafted-field"
      data-drafted={drafted || undefined}
      className={cn('relative min-w-0', drafted && DRAFTED_FRAME, className)}
    >
      {children}
      {drafted && (
        <DraftedBadge
          onUndo={onUndo}
          fieldLabel={fieldLabel}
          undoDisabled={undoDisabled}
          className="absolute -top-2.5 right-3 z-10"
        />
      )}
    </div>
  );
}

/**
 * A SettingRow the drafter may set: while `drafted` (with an `onUndo`), a
 * DraftedBadge follows its title and the row is marked `data-drafted`.
 *
 * Args:
 *   drafted: Whether the row's control holds a drafted value.
 *   onUndo: Undo for the badge; without it the row shows no badge.
 *   fieldLabel: The row's name for the undo button; the title when it is
 *     text.
 *   props: The SettingRow's own props.
 */
export function DraftedSettingRow({
  drafted,
  onUndo,
  fieldLabel,
  ...props
}: Omit<SettingRowProps, 'drafted' | 'onUndo' | 'fieldLabel'> & {
  drafted: boolean;
  onUndo?: () => void;
  fieldLabel?: string;
}) {
  const shown = drafted && !!onUndo;
  return (
    <SettingRow
      {...props}
      data-drafted={shown || undefined}
      titleAddon={
        shown ? (
          <DraftedBadge
            onUndo={onUndo}
            fieldLabel={
              fieldLabel ?? (typeof props.label === 'string' ? props.label : '')
            }
          />
        ) : (
          props.titleAddon
        )
      }
    />
  );
}
