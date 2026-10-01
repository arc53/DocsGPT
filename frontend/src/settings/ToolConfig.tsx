import { ChevronRight, CircleCheck, CircleX, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfigFields from '../components/ConfigFields';
import ViewOnlyNotice from '../components/ViewOnlyNotice';
import SearchInput from '../components/SearchInput';
import { Alert, AlertDescription } from '../components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Collapsible } from '../components/ui/collapsible';
import { EmptyState } from '../components/ui/empty-state';
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import { SectionHeader } from '../components/ui/section-header';
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import AddActionModal from '../modals/AddActionModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { actionTitle } from '../connectors/i18n';
import PermissionGroup, {
  PermissionSelect,
} from '../connectors/PermissionGroup';
import type { ActionPermission } from '../connectors/types';
import DetailBreadcrumb from '../navigation/DetailBreadcrumb';
import ImportSpecModal from '../modals/ImportSpecModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { getMethodBadgeVariant } from '../utils/httpMethodColors';
import { can, isOwner } from '../utils/accessUtils';
import { isSharedOAuthMcp } from '../utils/toolUtils';
import { areObjectsEqual } from '../utils/objectUtils';
import { cn, focusRing } from '@/lib/utils';
import { APIActionType, APIToolType, UserToolType } from './types';

const BODY_TYPE_HINT_KEYS: Record<string, string> = {
  'application/json': 'json',
  'application/x-www-form-urlencoded': 'formUrlencoded',
  'multipart/form-data': 'multipart',
  'text/plain': 'text',
  'application/xml': 'xml',
  'application/octet-stream': 'octetStream',
};

/**
 * What the caller may change on the open tool (`utils/accessUtils` `can`):
 * `canEdit` covers the name and the actions, `canEditCredentials` the
 * secrets, URLs and header / query values, and `canFixValues` whether a
 * parameter is filled by the AI or fixed, and its fixed value (the owner's
 * alone: the server refuses anyone else).
 */
const ToolAccessContext = React.createContext({
  canEdit: true,
  canEditCredentials: true,
  canFixValues: true,
});

type Access = 'read' | 'write';
type Permissioned = { active: boolean; require_approval?: boolean };

/** An action's permission from its stored flags (as the server reads them). */
const permissionOf = (action: Permissioned): ActionPermission =>
  action.active === false ? 'off' : action.require_approval ? 'ask' : 'always';

/** The action with `permission` written onto its `active` / `require_approval`. */
function withPermission<T extends Permissioned>(
  action: T,
  permission: ActionPermission,
): T {
  return {
    ...action,
    active: permission !== 'off',
    require_approval: permission === 'ask',
  };
}

/**
 * Whether an API tool action reads or writes: by its HTTP method, as
 * `connectors/permissions.py` `action_access` decides.
 */
const apiActionAccess = (action: APIActionType): Access =>
  ['GET', 'HEAD', 'OPTIONS'].includes((action.method || '').toUpperCase())
    ? 'read'
    : 'write';

/**
 * Splits `items` into the drawer's two groups, reads then writes, dropping
 * an empty one. An action without a declared access counts as a write, the
 * server's own default.
 */
function accessGroups<T>(
  items: T[],
  accessOf: (item: T) => Access | undefined,
) {
  return (['read', 'write'] as const)
    .map((access) => ({
      access,
      items: items.filter((item) => (accessOf(item) ?? 'write') === access),
    }))
    .filter((group) => group.items.length > 0);
}

/**
 * The ToggleGroup header of one access group on the Tools page editor,
 * the same skeleton as the connection drawer's permissions.
 */
function groupProps(
  t: (key: string, options?: Record<string, unknown>) => string,
  access: Access,
  count: number,
) {
  const name = t(`settings.connectors.capabilityPlain.${access}`);
  return {
    'data-access': access,
    title: name,
    count,
    groupLabel: t('settings.connectors.permission.groupLabel', { group: name }),
  };
}

/** Maps a body content type to its hint's locale key suffix (JSON by default). */
function bodyTypeHintKey(contentType?: string): string {
  return BODY_TYPE_HINT_KEYS[contentType || 'application/json'] ?? 'json';
}

/**
 * Who fills a parameter in: the AI, or a value that is always used (the
 * drawer's words); stored as `filled_by_llm`.
 */
function FilledBySelect({
  parameter,
  filledByLlm,
  disabled,
  onChange,
}: {
  parameter: string;
  filledByLlm: boolean;
  disabled: boolean;
  onChange: (filledByLlm: boolean) => void;
}) {
  const { t } = useTranslation();
  return (
    <Select
      value={filledByLlm ? 'ai' : 'fixed'}
      disabled={disabled}
      onValueChange={(value) => onChange(value === 'ai')}
    >
      <SelectTrigger
        size="sm"
        className="w-36"
        aria-label={t('settings.connectors.parameters.choiceLabel', {
          parameter,
          interpolation: { escapeValue: false },
        })}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="ai">
          {t('settings.connectors.parameters.ai')}
        </SelectItem>
        <SelectItem value="fixed">
          {t('settings.connectors.parameters.fixed')}
        </SelectItem>
      </SelectContent>
    </Select>
  );
}

export default function ToolConfig({
  tool,
  setTool,
  handleGoBack,
}: {
  tool: UserToolType | APIToolType;
  setTool: (tool: UserToolType | APIToolType) => void;
  handleGoBack: () => void;
}) {
  const token = useSelector(selectToken);
  const configRequirements = React.useMemo(
    () => tool.configRequirements ?? {},
    [tool.configRequirements],
  );
  const [configValues, setConfigValues] = React.useState<{
    [key: string]: any;
  }>(() => {
    const vals: { [key: string]: any } = {};
    const cfg = tool.config as { [key: string]: any } | undefined;
    Object.keys(configRequirements).forEach((key) => {
      if (cfg && key in cfg) {
        vals[key] = cfg[key];
      }
    });
    return vals;
  });
  const [customName, setCustomName] = React.useState<string>(
    tool.customName || '',
  );
  const [actionModalState, setActionModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [importModalState, setImportModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [initialState, setInitialState] = React.useState({
    customName: tool.customName || '',
    configValues: { ...configValues } as { [key: string]: any },
    config: tool.config,
    actions: 'actions' in tool ? tool.actions : [],
  });
  const [hasUnsavedChanges, setHasUnsavedChanges] = React.useState(false);
  const [showUnsavedModal, setShowUnsavedModal] = React.useState(false);
  const [configErrors, setConfigErrors] = React.useState<{
    [key: string]: string;
  }>({});
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState('');
  const [userActionsSearch, setUserActionsSearch] = React.useState('');
  const [expandedUserActions, setExpandedUserActions] = React.useState<
    Set<number>
  >(new Set());
  const { t } = useTranslation();
  const canEdit = can(tool, 'edit');
  // A shared OAuth server's connection stays with its owner (the backend
  // refuses it), so its fields lock like credentials the caller can't change.
  const sharedOAuth = isSharedOAuthMcp(tool);
  // A connected tool's secret lives on the owner's connection, which the
  // server lets only its owner change, whatever the owner's switch says.
  const ownerOnlyConnection =
    'connection_id' in tool && !!tool.connection_id && !isOwner(tool);
  const canEditCredentials =
    can(tool, 'edit_credentials') && !sharedOAuth && !ownerOnlyConnection;
  // Neither: the tool opens as a read-only view with no Save.
  const readOnly = !canEdit && !canEditCredentials;
  const canFixValues = isOwner(tool);
  const access = React.useMemo(
    () => ({ canEdit, canEditCredentials, canFixValues }),
    [canEdit, canEditCredentials, canFixValues],
  );

  const actionIdBase = React.useId();
  const toggleUserActionExpand = (index: number) => {
    setExpandedUserActions((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(index)) {
        newSet.delete(index);
      } else {
        newSet.add(index);
      }
      return newSet;
    });
  };

  const filteredUserActions = React.useMemo(() => {
    if (!('actions' in tool) || !tool.actions) return [];
    const query = userActionsSearch.toLowerCase();
    return tool.actions
      .map((action, index) => ({ action, originalIndex: index }))
      .filter(
        ({ action }) =>
          action.name.toLowerCase().includes(query) ||
          action.description?.toLowerCase().includes(query),
      )
      .sort((a, b) => a.action.name.localeCompare(b.action.name));
  }, [tool, userActionsSearch]);

  const handleBackClick = () => {
    if (hasUnsavedChanges) {
      setShowUnsavedModal(true);
    } else {
      handleGoBack();
    }
  };

  const handleFieldChange = (key: string, value: any) => {
    setConfigValues((prev) => ({ ...prev, [key]: value }));
    if (configErrors[key]) setConfigErrors((prev) => ({ ...prev, [key]: '' }));
  };

  const validateConfig = () => {
    if (tool.name === 'api_tool') return true;
    const newErrors: { [key: string]: string } = {};
    Object.entries(configRequirements).forEach(([key, spec]) => {
      if (spec.depends_on) {
        const visible = Object.entries(spec.depends_on).every(
          ([dk, dv]) => configValues[dk] === dv,
        );
        if (!visible) return;
      }
      if (spec.required && !configValues[key]?.toString().trim()) {
        const hasEncCreds = !!(tool as any).config?.has_encrypted_credentials;
        if (!(spec.secret && hasEncCreds)) {
          newErrors[key] = t('settings.tools.configErrors.required', {
            field: spec.label || key,
          });
        }
      }
      if (
        spec.type === 'number' &&
        configValues[key] !== undefined &&
        configValues[key] !== ''
      ) {
        const num = Number(configValues[key]);
        if (isNaN(num) || num < 1) {
          newErrors[key] = t('settings.tools.configErrors.positiveNumber');
        }
        if (key === 'timeout' && num > 300) {
          newErrors[key] = t('settings.tools.configErrors.maxTimeout');
        }
      }
    });
    setConfigErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const buildConfigToSave = () => {
    if (tool.name === 'api_tool') return tool.config;
    const config: { [key: string]: any } = {};
    Object.entries(configRequirements).forEach(([key, spec]) => {
      const val = configValues[key];
      if (val !== undefined && val !== '') {
        config[key] = val;
      } else if (spec.secret) {
        return;
      } else {
        const cfg = tool.config as { [key: string]: any } | undefined;
        if (cfg && key in cfg) {
          config[key] = cfg[key];
        } else if (spec.default !== undefined) {
          config[key] = spec.default;
        }
      }
    });
    return config;
  };

  React.useEffect(() => {
    const currentState = {
      customName,
      configValues,
      config: tool.config,
      actions: 'actions' in tool ? tool.actions : [],
    };

    setHasUnsavedChanges(!areObjectsEqual(initialState, currentState));
  }, [customName, configValues, tool]);

  const handleFilledByChange = (
    actionIndex: number,
    property: string,
    newFilledByLlm: boolean,
  ) => {
    setTool({
      ...tool,
      actions:
        'actions' in tool
          ? tool.actions.map((action, index) => {
              if (index === actionIndex) {
                return {
                  ...action,
                  parameters: {
                    ...action.parameters,
                    properties: {
                      ...action.parameters.properties,
                      [property]: {
                        ...action.parameters.properties[property],
                        filled_by_llm: newFilledByLlm,
                        required: newFilledByLlm,
                      },
                    },
                  },
                };
              }
              return action;
            })
          : [],
    });
  };

  /** Sets these actions (by index) to one permission, for Save to store. */
  const setUserPermissions = (
    indices: number[],
    permission: ActionPermission,
  ) => {
    if (!('actions' in tool)) return;
    setTool({
      ...tool,
      actions: tool.actions.map((action, index) =>
        indices.includes(index) ? withPermission(action, permission) : action,
      ),
    });
  };

  const userGroups = accessGroups(
    'actions' in tool && tool.actions
      ? tool.actions.map((action, originalIndex) => ({ action, originalIndex }))
      : [],
    ({ action }) => action.access,
  );

  // Saves the tool; a draft without an id (a new OpenAPI tool) is created
  // on its first save, so leaving without saving leaves nothing behind. A
  // non-2xx response throws so the caller shows it.
  const persistTool = async (configToSave: Record<string, unknown>) => {
    const payload = {
      name: tool.name,
      displayName: tool.displayName,
      customName: customName,
      description: tool.description,
      // Locked config isn't sent, so a rename or action edit still saves.
      ...((canEditCredentials || tool.name === 'api_tool') && {
        config: configToSave,
      }),
      actions: 'actions' in tool ? tool.actions : [],
      status: tool.status,
    };
    const response = tool.id
      ? await userService.updateTool({ id: tool.id, ...payload }, token)
      : await userService.createTool(payload, token);
    if (!response?.ok) throw new Error('Failed to save tool');
  };

  const handleSaveChanges = async () => {
    if (!validateConfig()) return;
    const configToSave = buildConfigToSave();

    setSaving(true);
    setSaveError('');

    try {
      await persistTool(configToSave);
      setInitialState({
        customName,
        configValues: { ...configValues },
        config: tool.config,
        actions: 'actions' in tool ? tool.actions : [],
      });
      setHasUnsavedChanges(false);
      handleGoBack();
    } catch {
      setSaveError(t('settings.tools.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const handleAddNewAction = (actionName: string) => {
    const toolCopy = tool as APIToolType;

    if (toolCopy.config.actions && toolCopy.config.actions[actionName]) {
      alert(t('settings.tools.actionAlreadyExists'));
      return;
    }

    const newAction: APIActionType = {
      name: actionName,
      method: 'GET',
      url: '',
      description: '',
      body: {
        properties: {},
        type: 'object',
      },
      headers: {
        properties: {},
        type: 'object',
      },
      query_params: {
        properties: {},
        type: 'object',
      },
      active: true,
      body_content_type: 'application/json',
      body_encoding_rules: {},
    };

    setTool({
      ...toolCopy,
      config: {
        ...toolCopy.config,
        actions: { ...toolCopy.config.actions, [actionName]: newAction },
      },
    });
  };

  const handleImportActions = (actions: APIActionType[]) => {
    const toolCopy = tool as APIToolType;
    const existingActions = toolCopy.config.actions || {};
    const newActions: { [key: string]: APIActionType } = {};

    actions.forEach((action) => {
      let actionName = action.name;
      let counter = 1;
      while (existingActions[actionName] || newActions[actionName]) {
        actionName = `${action.name}_${counter}`;
        counter++;
      }
      newActions[actionName] = { ...action, name: actionName };
    });

    setTool({
      ...toolCopy,
      config: {
        ...toolCopy.config,
        actions: { ...existingActions, ...newActions },
      },
    });
  };
  return (
    <div className="scrollbar-overlay flex flex-col gap-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <DetailBreadcrumb
          parentLabel={t('settings.tools.label')}
          currentLabel={tool.customName || tool.displayName || tool.name}
          onParentClick={handleBackClick}
        />
        {!readOnly && (
          <Button
            type="button"
            size="sm"
            shape="pill"
            onClick={handleSaveChanges}
            // A draft (no id yet) is saved to create it.
            disabled={!hasUnsavedChanges && !!tool.id}
            loading={saving}
          >
            {t('settings.tools.save')}
          </Button>
        )}
      </div>
      {readOnly && <ViewOnlyNotice />}
      {!readOnly && !canEditCredentials && (
        <ViewOnlyNotice
          message={
            sharedOAuth
              ? t('settings.tools.mcp.sharedOAuthOwnerOnly')
              : t('common.credentialsLockedNotice')
          }
        />
      )}
      {saveError && (
        <Alert variant="destructive" className="mb-2">
          <AlertDescription>{saveError}</AlertDescription>
        </Alert>
      )}
      <FormField
        label={t('settings.tools.customName')}
        labelSurface="background"
        className="mt-4 w-full max-w-96"
      >
        <Input
          type="text"
          value={customName}
          onChange={(e) => setCustomName(e.target.value)}
          placeholder={t('settings.tools.customNamePlaceholder')}
          disabled={!canEdit}
        />
      </FormField>
      <div className="mt-1">
        {tool.name !== 'api_tool' &&
          Object.keys(configRequirements).length > 0 && (
            <div className="flex flex-col gap-4">
              <SectionHeader
                as="h3"
                size="xs"
                title={t('settings.tools.authentication')}
              />
              <fieldset
                disabled={!canEditCredentials}
                className="max-w-96 min-w-0"
              >
                <ConfigFields
                  labelSurface="background"
                  configRequirements={configRequirements}
                  values={configValues}
                  onChange={handleFieldChange}
                  errors={configErrors}
                  isEditing
                  hasEncryptedCredentials={
                    !!(tool as any).config?.has_encrypted_credentials
                  }
                />
              </fieldset>
            </div>
          )}
      </div>
      <div className="flex flex-col gap-4">
        <div className="bg-border mx-0 my-2 h-[0.8px] w-full rounded-full"></div>
        <SectionHeader
          title={t('settings.tools.actions')}
          actions={
            tool.name === 'api_tool' && canEdit ? (
              <>
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={() => setImportModalState('ACTIVE')}
                >
                  {t('settings.tools.importSpec')}
                </Button>
                <Button
                  type="button"
                  variant="outline-primary"
                  shape="pill"
                  onClick={() => setActionModalState('ACTIVE')}
                >
                  {t('settings.tools.addAction')}
                </Button>
              </>
            ) : null
          }
        />
        {tool.name === 'api_tool' ? (
          <>
            {tool.config.actions &&
            Object.keys(tool.config.actions).length > 0 ? (
              <ToolAccessContext.Provider value={access}>
                <APIToolConfig tool={tool as APIToolType} setTool={setTool} />
              </ToolAccessContext.Provider>
            ) : (
              <EmptyState
                size="sm"
                title={t('settings.tools.noActionsFound')}
              />
            )}
          </>
        ) : (
          <div className="flex flex-col gap-4">
            {'actions' in tool && tool.actions && tool.actions.length > 0 ? (
              <>
                <SearchInput
                  value={userActionsSearch}
                  onChange={(e) => setUserActionsSearch(e.target.value)}
                  label={t('settings.tools.searchActions')}
                />

                {filteredUserActions.length === 0 && userActionsSearch && (
                  <EmptyState
                    size="xs"
                    illustration="none"
                    title={t('settings.tools.noActionsMatch')}
                  />
                )}

                {userGroups.map((group) => {
                  const inGroup = new Set(
                    group.items.map((item) => item.originalIndex),
                  );
                  const shown = filteredUserActions.filter((item) =>
                    inGroup.has(item.originalIndex),
                  );
                  if (shown.length === 0) return null;
                  return (
                    <PermissionGroup
                      key={group.access}
                      {...groupProps(t, group.access, group.items.length)}
                      values={group.items.map((item) =>
                        permissionOf(item.action),
                      )}
                      disabled={!canEdit}
                      onChoose={(permission) =>
                        setUserPermissions([...inGroup], permission)
                      }
                    >
                      {(customizing) => (
                        <div className="flex flex-col gap-4">
                          {shown.map(({ action, originalIndex }) => {
                            const isExpanded =
                              expandedUserActions.has(originalIndex);
                            const bodyId = `${actionIdBase}-${originalIndex}`;
                            return (
                              <div
                                key={originalIndex}
                                className="border-border w-full min-w-0 rounded-xl border"
                              >
                                <div
                                  className={cn(
                                    'border-border flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors',
                                    isExpanded
                                      ? 'bg-secondary rounded-t-xl border-b'
                                      : 'hover:bg-accent rounded-xl',
                                  )}
                                >
                                  <button
                                    type="button"
                                    aria-expanded={isExpanded}
                                    aria-controls={bodyId}
                                    onClick={() =>
                                      toggleUserActionExpand(originalIndex)
                                    }
                                    className={cn(
                                      'flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-sm text-left outline-none',
                                      focusRing,
                                    )}
                                  >
                                    <ChevronRight
                                      aria-hidden
                                      className={cn(
                                        'text-muted-foreground size-4 shrink-0 transition-transform duration-200',
                                        isExpanded && 'rotate-90',
                                      )}
                                    />
                                    <span
                                      className="text-foreground font-semibold"
                                      title={action.name}
                                    >
                                      {actionTitle(action.name)}
                                    </span>
                                    {action.description && (
                                      <span
                                        className="text-muted-foreground hidden truncate text-sm md:block md:max-w-xs lg:max-w-md"
                                        title={action.description}
                                      >
                                        {action.description}
                                      </span>
                                    )}
                                  </button>
                                  <div className="flex items-center gap-3">
                                    {customizing && (
                                      <PermissionSelect
                                        value={permissionOf(action)}
                                        disabled={!canEdit}
                                        label={t(
                                          'settings.connectors.permission.label',
                                          {
                                            action: actionTitle(action.name),
                                          },
                                        )}
                                        onChange={(permission) =>
                                          setUserPermissions(
                                            [originalIndex],
                                            permission,
                                          )
                                        }
                                      />
                                    )}
                                  </div>
                                </div>
                                <Collapsible open={isExpanded} id={bodyId}>
                                  <fieldset
                                    disabled={!canEdit}
                                    className="min-w-0"
                                  >
                                    <div className="relative mt-5 w-full px-5">
                                      <Input
                                        type="text"
                                        className="w-full"
                                        label={t(
                                          'settings.tools.descriptionPlaceholder',
                                        )}
                                        labelSurface="background"
                                        value={action.description}
                                        onChange={(e) => {
                                          setTool({
                                            ...tool,
                                            actions: tool.actions.map(
                                              (act, index) => {
                                                if (index === originalIndex) {
                                                  return {
                                                    ...act,
                                                    description: e.target.value,
                                                  };
                                                }
                                                return act;
                                              },
                                            ),
                                          });
                                        }}
                                      />
                                    </div>
                                    <div className="px-5 py-4">
                                      <TableContainer>
                                        <Table>
                                          <TableHead>
                                            <TableRow>
                                              <TableHeader>
                                                {t('settings.tools.fieldName')}
                                              </TableHeader>
                                              <TableHeader>
                                                {t('settings.tools.fieldType')}
                                              </TableHeader>
                                              <TableHeader>
                                                {t('settings.tools.filledBy')}
                                              </TableHeader>
                                              <TableHeader>
                                                {t(
                                                  'settings.tools.fieldDescription',
                                                )}
                                              </TableHeader>
                                              <TableHeader>
                                                {t('settings.tools.value')}
                                              </TableHeader>
                                            </TableRow>
                                          </TableHead>
                                          <TableBody>
                                            {Object.entries(
                                              action.parameters?.properties,
                                            ).map((param, paramIndex) => {
                                              const uniqueKey = `${originalIndex}-${param[0]}`;
                                              return (
                                                <TableRow key={paramIndex}>
                                                  <TableCell className="text-nowrap">
                                                    {param[0]}
                                                  </TableCell>
                                                  <TableCell className="text-nowrap">
                                                    {param[1].type}
                                                  </TableCell>
                                                  <TableCell>
                                                    <FilledBySelect
                                                      parameter={param[0]}
                                                      filledByLlm={
                                                        param[1].filled_by_llm
                                                      }
                                                      disabled={!canFixValues}
                                                      onChange={(filled) =>
                                                        handleFilledByChange(
                                                          originalIndex,
                                                          param[0],
                                                          filled,
                                                        )
                                                      }
                                                    />
                                                  </TableCell>
                                                  <TableCell>
                                                    <Input
                                                      key={uniqueKey}
                                                      value={
                                                        param[1].description
                                                      }
                                                      size="sm"
                                                      onChange={(e) => {
                                                        setTool({
                                                          ...tool,
                                                          actions:
                                                            tool.actions.map(
                                                              (act, index) => {
                                                                if (
                                                                  index ===
                                                                  originalIndex
                                                                ) {
                                                                  return {
                                                                    ...act,
                                                                    parameters:
                                                                      {
                                                                        ...act.parameters,
                                                                        properties:
                                                                          {
                                                                            ...act
                                                                              .parameters
                                                                              .properties,
                                                                            [param[0]]:
                                                                              {
                                                                                ...act
                                                                                  .parameters
                                                                                  .properties[
                                                                                  param[0]
                                                                                ],
                                                                                description:
                                                                                  e
                                                                                    .target
                                                                                    .value,
                                                                              },
                                                                          },
                                                                      },
                                                                  };
                                                                }
                                                                return act;
                                                              },
                                                            ),
                                                        });
                                                      }}
                                                    />
                                                  </TableCell>
                                                  <TableCell>
                                                    <Input
                                                      value={param[1].value}
                                                      key={uniqueKey}
                                                      disabled={
                                                        param[1]
                                                          .filled_by_llm ||
                                                        !canFixValues
                                                      }
                                                      size="sm"
                                                      onChange={(e) => {
                                                        setTool({
                                                          ...tool,
                                                          actions:
                                                            tool.actions.map(
                                                              (act, index) => {
                                                                if (
                                                                  index ===
                                                                  originalIndex
                                                                ) {
                                                                  return {
                                                                    ...act,
                                                                    parameters:
                                                                      {
                                                                        ...act.parameters,
                                                                        properties:
                                                                          {
                                                                            ...act
                                                                              .parameters
                                                                              .properties,
                                                                            [param[0]]:
                                                                              {
                                                                                ...act
                                                                                  .parameters
                                                                                  .properties[
                                                                                  param[0]
                                                                                ],
                                                                                value:
                                                                                  e
                                                                                    .target
                                                                                    .value,
                                                                              },
                                                                          },
                                                                      },
                                                                  };
                                                                }
                                                                return act;
                                                              },
                                                            ),
                                                        });
                                                      }}
                                                    />
                                                  </TableCell>
                                                </TableRow>
                                              );
                                            })}
                                          </TableBody>
                                        </Table>
                                      </TableContainer>
                                    </div>
                                  </fieldset>
                                </Collapsible>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </PermissionGroup>
                  );
                })}
              </>
            ) : (
              <EmptyState
                size="sm"
                title={t('settings.tools.noActionsFound')}
              />
            )}
          </div>
        )}
        <AddActionModal
          modalState={actionModalState}
          setModalState={setActionModalState}
          handleSubmit={handleAddNewAction}
        />
        <ImportSpecModal
          modalState={importModalState}
          setModalState={setImportModalState}
          onImport={handleImportActions}
        />
        {showUnsavedModal && (
          <ConfirmationModal
            message={t('settings.tools.unsavedChanges')}
            modalState="ACTIVE"
            setModalState={(state) => setShowUnsavedModal(state === 'ACTIVE')}
            submitLabel={t('settings.tools.saveAndLeave')}
            // Pending while the save runs; a failed save rejects, so the
            // error stays in this dialog and the page stays put.
            handleSubmit={async () => {
              if (!validateConfig()) {
                setShowUnsavedModal(false);
                return;
              }
              const configToSave = buildConfigToSave();
              setSaving(true);
              setSaveError('');

              try {
                await persistTool(configToSave);
              } finally {
                setSaving(false);
              }
              setShowUnsavedModal(false);
              handleGoBack();
            }}
            error={t('settings.tools.saveFailed')}
            cancelLabel={t('settings.tools.leaveWithoutSaving')}
            handleCancel={() => {
              setShowUnsavedModal(false);
              handleGoBack();
            }}
          />
        )}
      </div>
    </div>
  );
}

function APIToolConfig({
  tool,
  setTool,
}: {
  tool: APIToolType;
  setTool: (tool: APIToolType) => void;
}) {
  const [apiTool, setApiTool] = React.useState<APIToolType>(tool);
  const { t } = useTranslation();
  const { canEdit, canEditCredentials } = React.useContext(ToolAccessContext);
  const [actionToDelete, setActionToDelete] = React.useState<string | null>(
    null,
  );
  const [deleteModalState, setDeleteModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [expandedActions, setExpandedActions] = React.useState<Set<string>>(
    new Set(),
  );

  const actionIdBase = React.useId();
  const toggleActionExpand = (actionName: string) => {
    setExpandedActions((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(actionName)) {
        newSet.delete(actionName);
      } else {
        newSet.add(actionName);
      }
      return newSet;
    });
  };

  const filteredActions = React.useMemo(() => {
    if (!apiTool.config.actions) return [];
    const entries = Object.entries(apiTool.config.actions);
    const filtered = entries.filter(([actionName, action]) => {
      const query = searchQuery.toLowerCase();
      return (
        actionName.toLowerCase().includes(query) ||
        action.name.toLowerCase().includes(query) ||
        action.description?.toLowerCase().includes(query) ||
        action.url?.toLowerCase().includes(query)
      );
    });
    return filtered.sort((a, b) => a[0].localeCompare(b[0]));
  }, [apiTool.config.actions, searchQuery]);

  const handleDeleteActionClick = (actionName: string) => {
    setActionToDelete(actionName);
    setDeleteModalState('ACTIVE');
  };
  const handleConfirmedDelete = () => {
    if (actionToDelete) {
      setApiTool((prevApiTool) => {
        const { [actionToDelete]: deletedAction, ...remainingActions } =
          prevApiTool.config.actions;
        return {
          ...prevApiTool,
          config: {
            ...prevApiTool.config,
            actions: remainingActions,
          },
        };
      });
      setActionToDelete(null);
      setDeleteModalState('INACTIVE');
    }
  };

  const handleActionChange = (
    actionName: string,
    updatedAction: APIActionType,
  ) => {
    setApiTool((prevApiTool) => {
      const updatedActions = { ...prevApiTool.config.actions };
      updatedActions[actionName] = updatedAction;
      return {
        ...prevApiTool,
        config: { ...prevApiTool.config, actions: updatedActions },
      };
    });
  };

  /** Sets these actions (by name) to one permission, for Save to store. */
  const setPermissions = (names: string[], permission: ActionPermission) => {
    setApiTool((prevApiTool) => {
      const updatedActions = { ...prevApiTool.config.actions };
      for (const name of names)
        updatedActions[name] = withPermission(updatedActions[name], permission);
      return {
        ...prevApiTool,
        config: { ...prevApiTool.config, actions: updatedActions },
      };
    });
  };

  const groups = accessGroups(
    Object.entries(apiTool.config.actions ?? {}),
    ([, action]) => apiActionAccess(action),
  );

  React.useEffect(() => {
    setApiTool(tool);
  }, [tool]);

  React.useEffect(() => {
    setTool(apiTool);
  }, [apiTool]);

  return (
    <div className="scrollbar-overlay flex flex-col gap-4">
      <SearchInput
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        label={t('settings.tools.searchActions')}
      />

      {filteredActions.length === 0 && searchQuery && (
        <EmptyState
          size="xs"
          illustration="none"
          title={t('settings.tools.noActionsMatch')}
        />
      )}

      {groups.map((group) => {
        const names = group.items.map(([name]) => name);
        const shown = filteredActions.filter(([name]) => names.includes(name));
        if (shown.length === 0) return null;
        return (
          <PermissionGroup
            key={group.access}
            {...groupProps(t, group.access, group.items.length)}
            values={group.items.map(([, action]) => permissionOf(action))}
            disabled={!canEdit}
            onChoose={(permission) => setPermissions(names, permission)}
          >
            {(customizing) => (
              <div className="flex flex-col gap-4">
                {shown.map(([actionName, action], index) => {
                  const isExpanded = expandedActions.has(actionName);
                  const bodyId = `${actionIdBase}-${index}`;
                  return (
                    <div
                      key={actionName}
                      className="border-border w-full min-w-0 rounded-xl border"
                    >
                      <div
                        className={cn(
                          'border-border flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors',
                          isExpanded
                            ? 'bg-secondary rounded-t-xl border-b'
                            : 'hover:bg-accent rounded-xl',
                        )}
                      >
                        <button
                          type="button"
                          aria-expanded={isExpanded}
                          aria-controls={bodyId}
                          onClick={() => toggleActionExpand(actionName)}
                          className={cn(
                            'flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-sm text-left outline-none',
                            focusRing,
                          )}
                        >
                          <ChevronRight
                            aria-hidden
                            className={cn(
                              'text-muted-foreground size-4 shrink-0 transition-transform duration-200',
                              isExpanded && 'rotate-90',
                            )}
                          />
                          <Badge variant={getMethodBadgeVariant(action.method)}>
                            {action.method}
                          </Badge>
                          <span
                            className="text-foreground font-semibold"
                            title={action.name}
                          >
                            {actionTitle(action.name)}
                          </span>
                          {action.description && (
                            <span
                              className="text-muted-foreground hidden truncate text-sm md:block md:max-w-xs lg:max-w-md"
                              title={action.description}
                            >
                              {action.description}
                            </span>
                          )}
                        </button>
                        <div className="flex items-center gap-2">
                          <IconButton
                            label={t('settings.tools.delete')}
                            icon={Trash2}
                            variant="ghost-destructive-on-accent"
                            size="icon-xs"
                            shape="pill"
                            disabled={!canEdit}
                            onClick={() => handleDeleteActionClick(actionName)}
                            className="mr-2"
                          />
                          {customizing && (
                            <PermissionSelect
                              value={permissionOf(action)}
                              disabled={!canEdit}
                              label={t('settings.connectors.permission.label', {
                                action: actionTitle(actionName),
                              })}
                              onChange={(permission) =>
                                setPermissions([actionName], permission)
                              }
                            />
                          )}
                        </div>
                      </div>
                      <Collapsible open={isExpanded} id={bodyId}>
                        <fieldset disabled={!canEdit} className="min-w-0">
                          <div className="mt-8 px-5">
                            <Input
                              type="text"
                              value={action.url}
                              disabled={!canEditCredentials}
                              onChange={(e) => {
                                setApiTool((prevApiTool) => {
                                  const updatedActions = {
                                    ...prevApiTool.config.actions,
                                  };
                                  const updatedAction = {
                                    ...updatedActions[actionName],
                                  };
                                  updatedAction.url = e.target.value;
                                  updatedActions[actionName] = updatedAction;
                                  return {
                                    ...prevApiTool,
                                    config: {
                                      ...prevApiTool.config,
                                      actions: updatedActions,
                                    },
                                  };
                                });
                              }}
                              label={t('settings.tools.urlPlaceholder')}
                              labelSurface="background"
                            />
                          </div>
                          <div className="mt-4 px-5 py-2">
                            <FormField
                              label={t('settings.tools.method')}
                              labelSurface="background"
                              className="w-full max-w-80"
                            >
                              <Select
                                value={action.method}
                                onValueChange={(value) => {
                                  setApiTool((prevApiTool) => {
                                    const updatedActions = {
                                      ...prevApiTool.config.actions,
                                    };
                                    const updatedAction = {
                                      ...updatedActions[actionName],
                                    };
                                    updatedAction.method = value as
                                      | 'GET'
                                      | 'POST'
                                      | 'PUT'
                                      | 'DELETE'
                                      | 'PATCH'
                                      | 'HEAD'
                                      | 'OPTIONS';
                                    updatedActions[actionName] = updatedAction;
                                    return {
                                      ...prevApiTool,
                                      config: {
                                        ...prevApiTool.config,
                                        actions: updatedActions,
                                      },
                                    };
                                  });
                                }}
                              >
                                <SelectTrigger className="w-full" size="field">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {[
                                    'GET',
                                    'POST',
                                    'PUT',
                                    'DELETE',
                                    'PATCH',
                                    'HEAD',
                                    'OPTIONS',
                                  ].map((m) => (
                                    <SelectItem key={m} value={m}>
                                      {m}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            </FormField>
                          </div>
                          <div className="mt-4 px-5 py-2">
                            <Input
                              type="text"
                              value={action.description}
                              onChange={(e) => {
                                setApiTool((prevApiTool) => {
                                  const updatedActions = {
                                    ...prevApiTool.config.actions,
                                  };
                                  const updatedAction = {
                                    ...updatedActions[actionName],
                                  };
                                  updatedAction.description = e.target.value;
                                  updatedActions[actionName] = updatedAction;
                                  return {
                                    ...prevApiTool,
                                    config: {
                                      ...prevApiTool.config,
                                      actions: updatedActions,
                                    },
                                  };
                                });
                              }}
                              label={t('settings.tools.descriptionPlaceholder')}
                              labelSurface="background"
                            />
                          </div>
                          {(action.method === 'POST' ||
                            action.method === 'PUT' ||
                            action.method === 'PATCH' ||
                            action.method === 'HEAD' ||
                            action.method === 'OPTIONS') && (
                            <div className="mt-4 px-5 py-2">
                              <FormField
                                label={t('settings.tools.bodyContentType')}
                                hint={t(
                                  `settings.tools.bodyTypeHint.${bodyTypeHintKey(
                                    action.body_content_type,
                                  )}`,
                                )}
                                labelSurface="background"
                                className="w-full max-w-80"
                              >
                                <Select
                                  value={
                                    action.body_content_type ||
                                    'application/json'
                                  }
                                  onValueChange={(value) => {
                                    setApiTool((prevApiTool) => {
                                      const updatedActions = {
                                        ...prevApiTool.config.actions,
                                      };
                                      const updatedAction = {
                                        ...updatedActions[actionName],
                                      };
                                      updatedAction.body_content_type =
                                        value as
                                          | 'application/json'
                                          | 'application/x-www-form-urlencoded'
                                          | 'multipart/form-data'
                                          | 'text/plain'
                                          | 'application/xml'
                                          | 'application/octet-stream';
                                      updatedActions[actionName] =
                                        updatedAction;
                                      return {
                                        ...prevApiTool,
                                        config: {
                                          ...prevApiTool.config,
                                          actions: updatedActions,
                                        },
                                      };
                                    });
                                  }}
                                >
                                  <SelectTrigger
                                    className="w-full"
                                    size="field"
                                  >
                                    <SelectValue />
                                  </SelectTrigger>
                                  <SelectContent>
                                    {[
                                      'application/json',
                                      'application/x-www-form-urlencoded',
                                      'multipart/form-data',
                                      'text/plain',
                                      'application/xml',
                                      'application/octet-stream',
                                    ].map((ct) => (
                                      <SelectItem key={ct} value={ct}>
                                        {ct}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </FormField>
                            </div>
                          )}
                          <div className="mt-4 px-5 py-2">
                            <APIActionTable
                              apiAction={action}
                              handleActionChange={handleActionChange}
                            />
                          </div>
                        </fieldset>
                      </Collapsible>
                    </div>
                  );
                })}
              </div>
            )}
          </PermissionGroup>
        );
      })}

      {deleteModalState === 'ACTIVE' && actionToDelete && (
        <ConfirmationModal
          message={t('settings.tools.deleteActionWarning', {
            interpolation: { escapeValue: false },
            name: actionToDelete,
          })}
          description={t('settings.tools.deleteActionConsequence')}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={handleConfirmedDelete}
          handleCancel={() => {
            setDeleteModalState('INACTIVE');
            setActionToDelete(null);
          }}
          submitLabel={t('settings.tools.delete')}
          variant="destructive"
        />
      )}
    </div>
  );
}

function APIActionTable({
  apiAction,
  handleActionChange,
}: {
  apiAction: APIActionType;
  handleActionChange: (
    actionName: string,
    updatedAction: APIActionType,
  ) => void;
}) {
  const { t } = useTranslation();
  const { canEditCredentials, canFixValues } =
    React.useContext(ToolAccessContext);

  const [action, setAction] = React.useState<APIActionType>(apiAction);
  const [newPropertyKey, setNewPropertyKey] = React.useState('');
  const [newPropertyType, setNewPropertyType] = React.useState<
    'string' | 'integer'
  >('string');
  const [addingPropertySection, setAddingPropertySection] = React.useState<
    'headers' | 'query_params' | 'body' | null
  >(null);
  const [editingPropertyKey, setEditingPropertyKey] = React.useState<{
    section: 'headers' | 'query_params' | 'body' | null;
    oldKey: string | null;
  }>({ section: null, oldKey: null });

  const handlePropertyChange = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
    field: 'value' | 'description' | 'filled_by_llm',
    value: string | number | boolean,
  ) => {
    setAction((prevAction) => {
      const currentProperty = prevAction[section].properties[key];
      const updatedProperty: typeof currentProperty = {
        ...currentProperty,
        [field]: value,
        ...(field === 'filled_by_llm' && typeof value === 'boolean'
          ? { required: value }
          : {}),
      };
      const updatedProperties = {
        ...prevAction[section].properties,
        [key]: updatedProperty,
      };
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: updatedProperties,
        },
      };
    });
  };

  const handleAddPropertyStart = (
    section: 'headers' | 'query_params' | 'body',
  ) => {
    setEditingPropertyKey({ section: null, oldKey: null });
    setAddingPropertySection(section);
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleAddPropertyCancel = () => {
    setAddingPropertySection(null);
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleAddProperty = () => {
    if (addingPropertySection && newPropertyKey.trim() !== '') {
      setAction((prevAction) => {
        const updatedProperties = {
          ...prevAction[addingPropertySection].properties,
          [newPropertyKey.trim()]: {
            type: newPropertyType,
            description: '',
            value: '',
            filled_by_llm: false,
            required: false,
          },
        };
        return {
          ...prevAction,
          [addingPropertySection]: {
            ...prevAction[addingPropertySection],
            properties: updatedProperties,
          },
        };
      });
      setNewPropertyKey('');
      setNewPropertyType('string');
      setAddingPropertySection(null);
    }
  };

  const handleRenamePropertyStart = (
    section: 'headers' | 'query_params' | 'body',
    oldKey: string,
  ) => {
    setAddingPropertySection(null);
    setEditingPropertyKey({ section, oldKey });
    setNewPropertyKey(oldKey);
  };
  const handleRenamePropertyCancel = () => {
    setEditingPropertyKey({ section: null, oldKey: null });
    setNewPropertyKey('');
    setNewPropertyType('string');
  };
  const handleRenameProperty = () => {
    if (
      editingPropertyKey.section &&
      editingPropertyKey.oldKey &&
      newPropertyKey.trim() !== '' &&
      newPropertyKey.trim() !== editingPropertyKey.oldKey
    ) {
      setAction((prevAction) => {
        const { section, oldKey } = editingPropertyKey;
        if (section && oldKey) {
          const { [oldKey]: oldProperty, ...restProperties } =
            prevAction[section].properties;
          const updatedProperties = {
            ...restProperties,
            [newPropertyKey.trim()]: oldProperty,
          };
          return {
            ...prevAction,
            [section]: {
              ...prevAction[section],
              properties: updatedProperties,
            },
          };
        }
        return prevAction;
      });
      setEditingPropertyKey({ section: null, oldKey: null });
      setNewPropertyKey('');
      setNewPropertyType('string');
    }
  };

  const handlePorpertyDelete = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
  ) => {
    setAction((prevAction) => {
      const { [key]: deletedProperty, ...restProperties } =
        prevAction[section].properties;
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: restProperties,
        },
      };
    });
  };

  const handlePropertyTypeChange = (
    section: 'headers' | 'query_params' | 'body',
    key: string,
    newType: 'string' | 'integer',
  ) => {
    setAction((prevAction) => {
      const updatedProperties = {
        ...prevAction[section].properties,
        [key]: {
          ...prevAction[section].properties[key],
          type: newType,
        },
      };
      return {
        ...prevAction,
        [section]: {
          ...prevAction[section],
          properties: updatedProperties,
        },
      };
    });
  };

  React.useEffect(() => {
    setAction(apiAction);
  }, [apiAction]);

  React.useEffect(() => {
    handleActionChange(action.name, action);
  }, [action]);
  const renderPropertiesTable = (
    section: 'headers' | 'query_params' | 'body',
  ) => {
    return (
      <>
        {Object.entries(action[section].properties).map(
          ([key, param], index) => (
            <TableRow key={index}>
              <TableCell className="relative">
                {editingPropertyKey.section === section &&
                editingPropertyKey.oldKey === key ? (
                  <div className="flex items-center gap-2">
                    <Input
                      value={newPropertyKey}
                      size="sm"
                      className="min-w-0 flex-1"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="flex shrink-0 gap-1">
                      <IconButton
                        label={t('settings.tools.save')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenameProperty}
                      >
                        <CircleCheck className="text-success" aria-hidden />
                      </IconButton>
                      <IconButton
                        label={t('settings.tools.cancel')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenamePropertyCancel}
                      >
                        <CircleX className="text-destructive" aria-hidden />
                      </IconButton>
                    </div>
                  </div>
                ) : (
                  <Input
                    value={key}
                    size="sm"
                    onFocus={() => handleRenamePropertyStart(section, key)}
                    readOnly
                  />
                )}
              </TableCell>
              <TableCell>
                <Select
                  value={param.type}
                  onValueChange={(value) =>
                    handlePropertyTypeChange(
                      section,
                      key,
                      value as 'string' | 'integer',
                    )
                  }
                >
                  <SelectTrigger
                    size="sm"
                    aria-label={t('settings.tools.type')}
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="string">string</SelectItem>
                    <SelectItem value="integer">integer</SelectItem>
                  </SelectContent>
                </Select>
              </TableCell>
              <TableCell>
                <FilledBySelect
                  parameter={key}
                  filledByLlm={param.filled_by_llm}
                  disabled={!canFixValues}
                  onChange={(filled) =>
                    handlePropertyChange(section, key, 'filled_by_llm', filled)
                  }
                />
              </TableCell>
              <TableCell>
                <Input
                  value={param.description}
                  size="sm"
                  onChange={(e) =>
                    handlePropertyChange(
                      section,
                      key,
                      'description',
                      e.target.value,
                    )
                  }
                />
              </TableCell>
              <TableCell>
                <Input
                  value={param.value}
                  disabled={
                    param.filled_by_llm ||
                    !canFixValues ||
                    (section === 'query_params' && !canEditCredentials)
                  }
                  onChange={(e) =>
                    handlePropertyChange(section, key, 'value', e.target.value)
                  }
                  {...(section === 'query_params' &&
                    param.has_value && {
                      type: 'password',
                      placeholder: t('settings.tools.savedSecretPlaceholder'),
                    })}
                  size="sm"
                />
              </TableCell>
              <TableCell width="40px" align="center">
                <IconButton
                  label={t('settings.tools.delete')}
                  icon={Trash2}
                  variant="ghost-destructive"
                  size="icon-xs"
                  onClick={() => handlePorpertyDelete(section, key)}
                />
              </TableCell>
            </TableRow>
          ),
        )}
        {addingPropertySection === section ? (
          <TableRow>
            <TableCell>
              <Input
                value={newPropertyKey}
                onChange={(e) => setNewPropertyKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleAddProperty();
                  }
                }}
                placeholder={t('settings.tools.propertyName')}
                size="sm"
              />
            </TableCell>
            <TableCell>
              <Select
                value={newPropertyType}
                onValueChange={(value) =>
                  setNewPropertyType(value as 'string' | 'integer')
                }
              >
                <SelectTrigger size="sm" aria-label={t('settings.tools.type')}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="string">string</SelectItem>
                  <SelectItem value="integer">integer</SelectItem>
                </SelectContent>
              </Select>
            </TableCell>
            <TableCell colSpan={3} className="text-right">
              <Button
                type="button"
                variant="default"
                size="sm"
                shape="pill"
                onClick={handleAddProperty}
                className="mr-1"
              >
                {t('settings.tools.add')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                shape="pill"
                onClick={handleAddPropertyCancel}
              >
                {t('settings.tools.cancel')}
              </Button>
            </TableCell>
            <TableCell width="40px" align="center"></TableCell>
          </TableRow>
        ) : (
          <TableRow>
            <TableCell colSpan={5}>
              <Button
                type="button"
                variant="outline-primary"
                size="sm"
                shape="pill"
                onClick={() => handleAddPropertyStart(section)}
              >
                {t('settings.tools.addNew')}
              </Button>
            </TableCell>
            <TableCell width="40px" align="center"></TableCell>
          </TableRow>
        )}
      </>
    );
  };

  const renderHeadersTable = () => {
    return (
      <>
        {Object.entries(action.headers.properties).map(
          ([key, param], index) => (
            <TableRow key={index}>
              <TableCell className="relative">
                {editingPropertyKey.section === 'headers' &&
                editingPropertyKey.oldKey === key ? (
                  <div className="flex items-center gap-2">
                    <Input
                      value={newPropertyKey}
                      size="sm"
                      className="min-w-0 flex-1"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="flex shrink-0 gap-1">
                      <IconButton
                        label={t('settings.tools.save')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenameProperty}
                      >
                        <CircleCheck className="text-success" aria-hidden />
                      </IconButton>
                      <IconButton
                        label={t('settings.tools.cancel')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenamePropertyCancel}
                      >
                        <CircleX className="text-destructive" aria-hidden />
                      </IconButton>
                    </div>
                  </div>
                ) : (
                  <Input
                    value={key}
                    size="sm"
                    onFocus={() => handleRenamePropertyStart('headers', key)}
                    readOnly
                  />
                )}
              </TableCell>
              <TableCell>
                <Input
                  value={param.value}
                  onChange={(e) =>
                    handlePropertyChange(
                      'headers',
                      key,
                      'value',
                      e.target.value,
                    )
                  }
                  // A saved value never comes back: empty keeps it.
                  type={param.has_value ? 'password' : 'text'}
                  placeholder={
                    param.has_value
                      ? t('settings.tools.savedSecretPlaceholder')
                      : t('settings.tools.headerValuePlaceholder')
                  }
                  disabled={!canEditCredentials}
                  size="sm"
                />
              </TableCell>
              <TableCell>
                <Input
                  value={param.description}
                  size="sm"
                  onChange={(e) =>
                    handlePropertyChange(
                      'headers',
                      key,
                      'description',
                      e.target.value,
                    )
                  }
                />
              </TableCell>
              <TableCell width="40px" align="center">
                <IconButton
                  label={t('settings.tools.delete')}
                  icon={Trash2}
                  variant="ghost-destructive"
                  size="icon-xs"
                  onClick={() => handlePorpertyDelete('headers', key)}
                />
              </TableCell>
            </TableRow>
          ),
        )}
        {addingPropertySection === 'headers' ? (
          <TableRow>
            <TableCell>
              <Input
                value={newPropertyKey}
                onChange={(e) => setNewPropertyKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handleAddProperty();
                  }
                }}
                placeholder={t('settings.tools.propertyName')}
                size="sm"
              />
            </TableCell>
            <TableCell colSpan={2} className="text-right">
              <Button
                type="button"
                variant="default"
                size="sm"
                shape="pill"
                onClick={handleAddProperty}
                className="mr-1"
              >
                {t('settings.tools.add')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                shape="pill"
                onClick={handleAddPropertyCancel}
              >
                {t('settings.tools.cancel')}
              </Button>
            </TableCell>
            <TableCell width="40px" align="center"></TableCell>
          </TableRow>
        ) : (
          <TableRow>
            <TableCell colSpan={3}>
              <Button
                type="button"
                variant="outline-primary"
                size="sm"
                shape="pill"
                onClick={() => handleAddPropertyStart('headers')}
              >
                {t('settings.tools.addNew')}
              </Button>
            </TableCell>
            <TableCell width="40px" align="center"></TableCell>
          </TableRow>
        )}
      </>
    );
  };

  return (
    <div className="scrollbar-overlay flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <SectionHeader as="h3" size="xs" title={t('settings.tools.headers')} />
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader width="14rem">
                  {t('settings.tools.name')}
                </TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader width="40px" align="center"></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>{renderHeadersTable()}</TableBody>
          </Table>
        </TableContainer>
      </div>
      <div className="flex flex-col gap-1">
        <SectionHeader
          as="h3"
          size="xs"
          title={t('settings.tools.queryParameters')}
        />
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader width="14rem">
                  {t('settings.tools.name')}
                </TableHeader>
                <TableHeader>{t('settings.tools.type')}</TableHeader>
                <TableHeader>{t('settings.tools.filledBy')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader width="40px" align="center"></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>{renderPropertiesTable('query_params')}</TableBody>
          </Table>
        </TableContainer>
      </div>
      <div className="mb-6 flex flex-col gap-1">
        <SectionHeader as="h3" size="xs" title={t('settings.tools.body')} />
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeader width="14rem">
                  {t('settings.tools.name')}
                </TableHeader>
                <TableHeader>{t('settings.tools.type')}</TableHeader>
                <TableHeader>{t('settings.tools.filledBy')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader width="40px" align="center"></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>{renderPropertiesTable('body')}</TableBody>
          </Table>
        </TableContainer>
      </div>
    </div>
  );
}
