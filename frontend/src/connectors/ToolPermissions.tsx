import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card } from '../components/ui/card';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { formatCount } from '../utils/dateTimeUtils';
import ActionParameters, { type ParameterValue } from './ActionParameters';
import { actionTitle } from './i18n';
import type {
  ActionPermission,
  ConnectionTool,
  ConnectionToolAction,
} from './types';

const PERMISSIONS: ActionPermission[] = ['always', 'ask', 'off'];

/** Longer groups start folded to their one group choice. */
const FOLD_AFTER = 5;

/**
 * One action under Customize: its name, what it does and its permission,
 * with its parameters one click away and a count of the values fixed there.
 */
function ActionRow({
  action,
  readOnly,
  onPermission,
  onParameters,
}: {
  action: ConnectionToolAction;
  readOnly: boolean;
  onPermission: (permission: ActionPermission) => void;
  onParameters: (changes: Record<string, ParameterValue>) => Promise<boolean>;
}) {
  const { t } = useTranslation();
  const [showParameters, setShowParameters] = useState(false);
  const parameters = action.parameters ?? [];
  const fixedCount = parameters.filter((parameter) => parameter.fixed).length;
  return (
    <li className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col items-start">
          <div className="flex max-w-full items-center gap-2">
            <p className="text-foreground truncate text-sm" title={action.name}>
              {actionTitle(action.name)}
            </p>
            {fixedCount > 0 && (
              <Badge variant="neutral">
                {t('settings.connectors.parameters.fixedCount', {
                  count: fixedCount,
                  formatted: formatCount(fixedCount),
                })}
              </Badge>
            )}
          </div>
          {action.description && (
            <p
              className="text-muted-foreground line-clamp-2 text-xs"
              title={action.description}
            >
              {action.description}
            </p>
          )}
          {parameters.length > 0 && (
            <Button
              type="button"
              variant="link"
              size="inline"
              className="mt-1"
              aria-expanded={showParameters}
              onClick={() => setShowParameters(!showParameters)}
            >
              {showParameters
                ? t('settings.connectors.parameters.hide')
                : t('settings.connectors.parameters.show')}
            </Button>
          )}
        </div>
        <Select
          value={action.permission}
          disabled={readOnly}
          onValueChange={(value) => onPermission(value as ActionPermission)}
        >
          <SelectTrigger
            size="sm"
            className="w-32 shrink-0"
            aria-label={t('settings.connectors.permission.label', {
              action: actionTitle(action.name),
            })}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERMISSIONS.map((permission) => (
              <SelectItem key={permission} value={permission}>
                {t(`settings.connectors.permission.${permission}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {showParameters && (
        <ActionParameters
          parameters={parameters}
          readOnly={readOnly}
          onSave={onParameters}
        />
      )}
    </li>
  );
}

/**
 * One tool's actions in two groups, what it looks up and what it does, each
 * set at once to Allow / Ask first / Off; single actions can differ under
 * Customize, where each action also opens its parameters to fix values the
 * AI must always use. Changes save immediately; a failed save puts the
 * previous choices back and says so.
 */
export default function ToolPermissions({
  connectionId,
  tool,
  onChange,
  readOnly = false,
  variant = 'outline',
}: {
  connectionId: string;
  tool: ConnectionTool;
  onChange?: (tool: ConnectionTool) => void;
  readOnly?: boolean;
  /** The panel surface: `outline` in a modal, `subtle` in the drawer. */
  variant?: 'outline' | 'subtle';
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [actions, setActions] = useState<ConnectionToolAction[]>(tool.actions);
  const [unfolded, setUnfolded] = useState<Record<string, boolean>>({});
  // A refreshed tool brings its new list of actions.
  useEffect(() => setActions(tool.actions), [tool.actions]);

  const setPermissions = (changes: Record<string, ActionPermission>) => {
    const previous = actions;
    setActions(
      actions.map((action) =>
        changes[action.name]
          ? { ...action, permission: changes[action.name] }
          : action,
      ),
    );
    connectorsService
      .setToolPermissions(connectionId, tool.id, changes, token)
      .then((data) => {
        if (!data?.success) throw new Error('save failed');
        onChange?.(data.tool);
      })
      .catch(() => {
        setActions(previous);
        dispatch(
          showActionToast({
            variant: 'destructive',
            message: t('settings.connectors.permission.saveFailed'),
          }),
        );
      });
  };

  const setParameters = async (
    actionName: string,
    changes: Record<string, ParameterValue>,
  ) => {
    try {
      const data = await connectorsService.setToolParameters(
        connectionId,
        tool.id,
        actionName,
        changes,
        token,
      );
      if (!data?.success) throw new Error('save failed');
      setActions(data.tool.actions);
      onChange?.(data.tool);
      return true;
    } catch {
      dispatch(
        showActionToast({
          variant: 'destructive',
          message: t('settings.connectors.parameters.saveFailed'),
        }),
      );
      return false;
    }
  };

  const groups = (['read', 'write'] as const)
    .map((access) => ({
      access,
      actions: actions.filter((action) => action.access === access),
    }))
    .filter((group) => group.actions.length > 0);

  return (
    <Card variant={variant} padding="sm" className="gap-4">
      {groups.map((group) => {
        const title = t(`settings.connectors.capabilityPlain.${group.access}`);
        const first = group.actions[0].permission;
        // One choice for the group when its actions agree; none when mixed.
        const common = group.actions.every(
          (action) => action.permission === first,
        )
          ? first
          : '';
        const foldable = group.actions.length > FOLD_AFTER;
        const open = !foldable || unfolded[group.access];
        return (
          <div
            key={group.access}
            data-access={group.access}
            className="flex flex-col gap-2"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <SectionHeader
                as="h4"
                size="sm"
                title={title}
                description={t('settings.connectors.permission.actionCount', {
                  count: group.actions.length,
                  formatted: formatCount(group.actions.length),
                })}
              />
              <div className="bg-muted rounded-full p-1">
                <ToggleGroup
                  type="single"
                  size="xs"
                  value={common}
                  disabled={readOnly}
                  aria-label={t('settings.connectors.permission.groupLabel', {
                    group: title,
                  })}
                  onValueChange={(value) =>
                    value &&
                    setPermissions(
                      Object.fromEntries(
                        group.actions.map((action) => [
                          action.name,
                          value as ActionPermission,
                        ]),
                      ),
                    )
                  }
                >
                  {PERMISSIONS.map((permission) => (
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
            </div>
            {foldable && (
              <Button
                type="button"
                variant="link"
                size="inline"
                className="self-start"
                aria-expanded={open}
                onClick={() =>
                  setUnfolded((state) => ({
                    ...state,
                    [group.access]: !open,
                  }))
                }
              >
                {open
                  ? t('settings.connectors.permission.fold')
                  : t('settings.connectors.permission.customize', {
                      count: group.actions.length,
                      formatted: formatCount(group.actions.length),
                    })}
              </Button>
            )}
            {open && (
              <ul className="flex flex-col gap-3">
                {group.actions.map((action) => (
                  <ActionRow
                    key={action.name}
                    action={action}
                    readOnly={readOnly}
                    onPermission={(permission) =>
                      setPermissions({ [action.name]: permission })
                    }
                    onParameters={(changes) =>
                      setParameters(action.name, changes)
                    }
                  />
                ))}
              </ul>
            )}
          </div>
        );
      })}
      <p className="text-muted-foreground text-xs">
        {t('settings.connectors.permission.hint')}
      </p>
    </Card>
  );
}
