import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import type { ActionPermission } from './types';

/** The group choice that shows each action's own control. */
export const CUSTOMIZE = 'customize';

/** Allow / Ask first / Off, in this order everywhere. */
export const PERMISSIONS: ActionPermission[] = ['always', 'ask', 'off'];

/** Where nobody can approve (API, widget, public link): Allow / Off. */
export const ALLOW_OR_OFF: ActionPermission[] = ['always', 'off'];

/**
 * One action's own permission, shown under Customize: a small Select with
 * the group's choices in the group's words.
 */
export function PermissionSelect({
  value,
  options = PERMISSIONS,
  onChange,
  disabled = false,
  label,
}: {
  value: ActionPermission;
  options?: ActionPermission[];
  onChange: (permission: ActionPermission) => void;
  disabled?: boolean;
  /** The accessible name, which names the action. */
  label: string;
}) {
  const { t } = useTranslation();
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as ActionPermission)}
    >
      <SelectTrigger size="sm" className="w-32 shrink-0" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((permission) => (
          <SelectItem key={permission} value={permission}>
            {t(`settings.connectors.permission.${permission}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/**
 * One action row: its name, a muted two-line description and its own
 * control; `children` goes under the text (a Parameters disclosure).
 */
export function PermissionRow({
  title,
  name,
  badge,
  description,
  control,
  children,
  after,
}: {
  title: ReactNode;
  /** The raw action name, shown on hover of the truncated title. */
  name?: string;
  /** Beside the title (a "1 fixed" count). */
  badge?: ReactNode;
  description?: string;
  control?: ReactNode;
  /** Under the name and description. */
  children?: ReactNode;
  /** Under the whole row, full width (an open parameter list). */
  after?: ReactNode;
}) {
  return (
    <li className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col items-start">
          <div className="flex max-w-full items-center gap-2">
            <p className="text-foreground truncate text-sm" title={name}>
              {title}
            </p>
            {badge}
          </div>
          {description && (
            <p className="text-muted-foreground line-clamp-2 text-xs">
              {description}
            </p>
          )}
          {children}
        </div>
        {control}
      </div>
      {after}
    </li>
  );
}

/**
 * One group of actions (what a tool looks up, what it does, what it may
 * change through the API): a `SectionHeader xs` title and one ToggleGroup
 * choice for all of them, plus Customize. Customize is pressed while the
 * actions disagree, and it is also the fold: `children` gets whether the
 * group is on Customize and shows each action's own control only then.
 * Once open, the group stays on Customize until a group choice is picked,
 * so a row the user just changed never folds away under them.
 */
export default function PermissionGroup({
  title,
  values,
  options = PERMISSIONS,
  onChoose,
  groupLabel,
  disabled = false,
  headingAs = 'h4',
  children,
  ...rest
}: {
  title: ReactNode;
  /** The title's heading level (h4 by default). */
  headingAs?: 'h3' | 'h4' | 'h5' | 'h6';
  /** Every action's current permission. */
  values: ActionPermission[];
  options?: ActionPermission[];
  /** Sets every action of the group to this permission. */
  onChoose: (permission: ActionPermission) => void;
  /** The group choice's accessible name. */
  groupLabel: string;
  disabled?: boolean;
  children: (customizing: boolean) => ReactNode;
  [data: `data-${string}`]: string | undefined;
}) {
  const { t } = useTranslation();
  const mixed = values.some((value) => value !== values[0]);
  const [customizing, setCustomizing] = useState(mixed);
  // Actions that come to disagree (a refresh, a row change) open the group.
  useEffect(() => {
    if (mixed) setCustomizing(true);
  }, [mixed]);
  const open = mixed || customizing;
  const value = open ? CUSTOMIZE : (values[0] ?? '');

  return (
    <div className="flex flex-col gap-3" {...rest}>
      <SectionHeader
        as={headingAs}
        size="xs"
        title={title}
        actions={
          <div className="bg-muted rounded-full p-1">
            <ToggleGroup
              type="single"
              size="xs"
              value={value}
              disabled={disabled}
              aria-label={groupLabel}
              onValueChange={(next) => {
                if (next === CUSTOMIZE) setCustomizing(true);
                // Clicking Customize again folds actions that agree.
                else if (!next) {
                  if (!mixed) setCustomizing(false);
                } else {
                  setCustomizing(false);
                  // Folding actions that already agree on it saves nothing.
                  if (mixed || next !== values[0])
                    onChoose(next as ActionPermission);
                }
              }}
            >
              {[...options, CUSTOMIZE].map((permission) => (
                <ToggleGroupItem
                  key={permission}
                  value={permission}
                  data-permission={permission}
                >
                  {t(`settings.connectors.permission.${permission}`)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        }
      />
      {children(open)}
    </div>
  );
}
