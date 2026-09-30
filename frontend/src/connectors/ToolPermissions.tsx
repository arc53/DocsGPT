import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import { Badge } from '../components/ui/badge';
import { Card } from '../components/ui/card';
import { showActionToast } from '../notifications/actionToastSlice';
import { selectToken } from '../preferences/preferenceSlice';
import { formatCount } from '../utils/dateTimeUtils';
import ActionParameters, {
  ActionParametersToggle,
  type ParameterValue,
} from './ActionParameters';
import { actionTitle } from './i18n';
import PermissionGroup, {
  PermissionRow,
  PermissionSelect,
} from './PermissionGroup';
import type {
  ActionPermission,
  ConnectionTool,
  ConnectionToolAction,
} from './types';

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
  const title = actionTitle(action.name);
  return (
    <PermissionRow
      title={title}
      name={action.name}
      description={action.description}
      badge={
        fixedCount > 0 && (
          <Badge variant="neutral">
            {t('settings.connectors.parameters.fixedCount', {
              count: fixedCount,
              formatted: formatCount(fixedCount),
            })}
          </Badge>
        )
      }
      control={
        <PermissionSelect
          value={action.permission}
          disabled={readOnly}
          onChange={onPermission}
          label={t('settings.connectors.permission.label', { action: title })}
        />
      }
      after={
        showParameters && (
          <ActionParameters
            parameters={parameters}
            readOnly={readOnly}
            onSave={onParameters}
          />
        )
      }
    >
      {parameters.length > 0 && (
        <ActionParametersToggle
          action={title}
          open={showParameters}
          onToggle={() => setShowParameters(!showParameters)}
        />
      )}
    </PermissionRow>
  );
}

/**
 * One tool's actions in two groups, what it looks up and what it does, each
 * set at once to Allow / Ask first / Off, or to Customize, which lists the
 * actions with their own choice and opens their parameters to fix values the
 * AI must always use. Changes save immediately; a failed save puts the
 * previous choices back and says so. `children` sits in the same card above
 * the groups (a tool-wide switch).
 */
export default function ToolPermissions({
  connectionId,
  tool,
  onChange,
  readOnly = false,
  variant = 'outline',
  groupHeadingAs = 'h4',
  children,
}: {
  connectionId: string;
  tool: ConnectionTool;
  onChange?: (tool: ConnectionTool) => void;
  readOnly?: boolean;
  /** The panel surface: `outline` in a modal, `subtle` in the drawer. */
  variant?: 'outline' | 'subtle';
  /** The groups' heading level, one below the surface's own headings. */
  groupHeadingAs?: 'h4' | 'h5' | 'h6';
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const token = useSelector(selectToken);
  const [actions, setActions] = useState<ConnectionToolAction[]>(tool.actions);
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
      {children}
      {groups.map((group) => {
        const name = t(`settings.connectors.capabilityPlain.${group.access}`);
        return (
          <PermissionGroup
            key={group.access}
            data-access={group.access}
            headingAs={groupHeadingAs}
            title={`${name} · ${formatCount(group.actions.length)}`}
            values={group.actions.map((action) => action.permission)}
            disabled={readOnly}
            groupLabel={t('settings.connectors.permission.groupLabel', {
              group: name,
            })}
            onChoose={(permission) =>
              setPermissions(
                Object.fromEntries(
                  group.actions.map((action) => [action.name, permission]),
                ),
              )
            }
          >
            {(customizing) =>
              customizing && (
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
              )
            }
          </PermissionGroup>
        );
      })}
    </Card>
  );
}
