import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import { Card } from '../components/ui/card';
import { SectionHeader } from '../components/ui/section-header';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { selectToken } from '../preferences/preferenceSlice';
import type {
  ActionPermission,
  ConnectionTool,
  ConnectionToolAction,
} from './types';

const PERMISSIONS: ActionPermission[] = ['always', 'ask', 'off'];

/**
 * One tool's actions, grouped Read and Write, each with Always allow /
 * Needs approval / Off. Changes save immediately; a failed save puts the
 * previous choice back.
 */
export default function ToolPermissions({
  connectionId,
  tool,
  onChange,
  readOnly = false,
}: {
  connectionId: string;
  tool: ConnectionTool;
  onChange?: (tool: ConnectionTool) => void;
  readOnly?: boolean;
}) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [actions, setActions] = useState<ConnectionToolAction[]>(tool.actions);

  const setPermission = (name: string, permission: ActionPermission) => {
    const previous = actions;
    const next = actions.map((action) =>
      action.name === name ? { ...action, permission } : action,
    );
    setActions(next);
    connectorsService
      .setToolPermissions(connectionId, tool.id, { [name]: permission }, token)
      .then((data) => {
        if (!data?.success) throw new Error('save failed');
        onChange?.(data.tool);
      })
      .catch(() => setActions(previous));
  };

  const groups = (['read', 'write'] as const)
    .map((access) => ({
      access,
      actions: actions.filter((action) => action.access === access),
    }))
    .filter((group) => group.actions.length > 0);

  return (
    <Card padding="sm" className="gap-4">
      {groups.map((group) => (
        <div key={group.access} className="flex flex-col gap-2">
          <SectionHeader
            as="h4"
            size="sm"
            title={t(`settings.connectors.capability.${group.access}`)}
          />
          <ul className="flex flex-col gap-2">
            {group.actions.map((action) => (
              <li
                key={action.name}
                className="flex items-center justify-between gap-3"
              >
                <span
                  className="text-foreground min-w-0 truncate font-mono text-xs"
                  title={action.description || action.name}
                >
                  {action.name}
                </span>
                <Select
                  value={action.permission}
                  disabled={readOnly}
                  onValueChange={(value) =>
                    setPermission(action.name, value as ActionPermission)
                  }
                >
                  <SelectTrigger
                    size="sm"
                    className="w-40 shrink-0"
                    aria-label={t('settings.connectors.permission.label', {
                      action: action.name,
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
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}
