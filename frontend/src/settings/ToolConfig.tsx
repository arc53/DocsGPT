import { ChevronRight, CircleCheck, CircleX, Trash2 } from 'lucide-react';
import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ConfigFields from '../components/ConfigFields';
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
import { Checkbox } from '../components/ui/checkbox';
import { EmptyState } from '../components/ui/empty-state';
import { FormField } from '../components/ui/form-field';
import { IconButton } from '../components/ui/icon-button';
import { Input } from '../components/ui/input';
import { SectionHeader } from '../components/ui/section-header';
import { Switch } from '../components/ui/switch';
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
import DetailBreadcrumb from '../navigation/DetailBreadcrumb';
import ImportSpecModal from '../modals/ImportSpecModal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { getMethodBadgeVariant } from '../utils/httpMethodColors';
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

/** Maps a body content type to its hint's locale key suffix (JSON by default). */
function bodyTypeHintKey(contentType?: string): string {
  return BODY_TYPE_HINT_KEYS[contentType || 'application/json'] ?? 'json';
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

  const handleCheckboxChange = (actionIndex: number, property: string) => {
    setTool({
      ...tool,
      actions:
        'actions' in tool
          ? tool.actions.map((action, index) => {
              if (index === actionIndex) {
                const newFilledByLlm =
                  !action.parameters.properties[property].filled_by_llm;
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

  const handleSaveChanges = async () => {
    if (!validateConfig()) return;
    const configToSave = buildConfigToSave();

    setSaving(true);
    setSaveError('');

    try {
      await userService.updateTool(
        {
          id: tool.id,
          name: tool.name,
          displayName: tool.displayName,
          customName: customName,
          description: tool.description,
          config: configToSave,
          actions: 'actions' in tool ? tool.actions : [],
          status: tool.status,
        },
        token,
      );
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

  const handleDelete = () => {
    userService.deleteTool({ id: tool.id }, token).then(() => {
      handleGoBack();
    });
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
        <Button
          type="button"
          size="sm"
          shape="pill"
          onClick={handleSaveChanges}
          disabled={!hasUnsavedChanges}
          loading={saving}
        >
          {t('settings.tools.save')}
        </Button>
      </div>
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
              <div className="max-w-96">
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
              </div>
            </div>
          )}
      </div>
      <div className="flex flex-col gap-4">
        <div className="bg-border mx-0 my-2 h-[0.8px] w-full rounded-full"></div>
        <SectionHeader
          title={t('settings.tools.actions')}
          actions={
            tool.name === 'api_tool' ? (
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
              <APIToolConfig tool={tool as APIToolType} setTool={setTool} />
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

                {filteredUserActions.map(({ action, originalIndex }) => {
                  const isExpanded = expandedUserActions.has(originalIndex);
                  return (
                    <div
                      key={originalIndex}
                      className="border-border w-full rounded-xl border"
                    >
                      <div
                        className={cn(
                          'border-border bg-muted flex cursor-pointer flex-wrap items-center justify-between px-4 py-3 outline-none',
                          isExpanded ? 'rounded-t-xl border-b' : 'rounded-xl',
                          focusRing,
                        )}
                        onClick={() => toggleUserActionExpand(originalIndex)}
                        role="button"
                        tabIndex={0}
                        aria-expanded={isExpanded}
                        onKeyDown={(e) => {
                          if (e.target !== e.currentTarget) return;
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            toggleUserActionExpand(originalIndex);
                          }
                        }}
                      >
                        <div className="flex items-center gap-3">
                          <ChevronRight
                            className={cn(
                              'text-muted-foreground size-4 transition-transform duration-200',
                              isExpanded && 'rotate-90',
                            )}
                          />
                          <p className="text-foreground font-semibold">
                            {action.name}
                          </p>
                          {action.description && (
                            <p className="text-muted-foreground hidden truncate text-sm md:block md:max-w-xs lg:max-w-md">
                              {action.description}
                            </p>
                          )}
                        </div>
                        <div
                          className="flex items-center gap-3"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex items-center gap-1">
                            <label
                              htmlFor={`approvalToggle-${originalIndex}`}
                              className="text-muted-foreground text-xs"
                            >
                              {t('settings.tools.requireApproval', 'Approval')}
                            </label>
                            <Switch
                              checked={action.require_approval ?? false}
                              onCheckedChange={(checked) => {
                                setTool({
                                  ...tool,
                                  actions: tool.actions.map((act, index) => {
                                    if (index === originalIndex) {
                                      return {
                                        ...act,
                                        require_approval: checked,
                                      };
                                    }
                                    return act;
                                  }),
                                });
                              }}
                              id={`approvalToggle-${originalIndex}`}
                            />
                          </div>
                          <Switch
                            checked={action.active}
                            onCheckedChange={(checked) => {
                              setTool({
                                ...tool,
                                actions: tool.actions.map((act, index) => {
                                  if (index === originalIndex) {
                                    return { ...act, active: checked };
                                  }
                                  return act;
                                }),
                              });
                            }}
                            id={`actionToggle-${originalIndex}`}
                            aria-label={t('settings.tools.toggleToolAria', {
                              toolName: action.name,
                            })}
                          />
                        </div>
                      </div>
                      {isExpanded && (
                        <>
                          <div className="relative mt-5 w-full px-5">
                            <Input
                              type="text"
                              className="w-full"
                              label={t('settings.tools.descriptionPlaceholder')}
                              labelSurface="background"
                              value={action.description}
                              onChange={(e) => {
                                setTool({
                                  ...tool,
                                  actions: tool.actions.map((act, index) => {
                                    if (index === originalIndex) {
                                      return {
                                        ...act,
                                        description: e.target.value,
                                      };
                                    }
                                    return act;
                                  }),
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
                                      {t('settings.tools.filledByLLM')}
                                    </TableHeader>
                                    <TableHeader>
                                      {t('settings.tools.fieldDescription')}
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
                                          <label
                                            htmlFor={uniqueKey}
                                            className="ml-2.5 flex cursor-pointer items-start gap-4"
                                          >
                                            <div className="flex items-center">
                                              &#8203;
                                              <Checkbox
                                                size="sm"
                                                checked={param[1].filled_by_llm}
                                                id={uniqueKey}
                                                aria-label={t(
                                                  'settings.tools.filledByLLM',
                                                )}
                                                onCheckedChange={() =>
                                                  handleCheckboxChange(
                                                    originalIndex,
                                                    param[0],
                                                  )
                                                }
                                              />
                                            </div>
                                          </label>
                                        </TableCell>
                                        <TableCell>
                                          <Input
                                            key={uniqueKey}
                                            value={param[1].description}
                                            size="sm"
                                            onChange={(e) => {
                                              setTool({
                                                ...tool,
                                                actions: tool.actions.map(
                                                  (act, index) => {
                                                    if (
                                                      index === originalIndex
                                                    ) {
                                                      return {
                                                        ...act,
                                                        parameters: {
                                                          ...act.parameters,
                                                          properties: {
                                                            ...act.parameters
                                                              .properties,
                                                            [param[0]]: {
                                                              ...act.parameters
                                                                .properties[
                                                                param[0]
                                                              ],
                                                              description:
                                                                e.target.value,
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
                                            disabled={param[1].filled_by_llm}
                                            size="sm"
                                            onChange={(e) => {
                                              setTool({
                                                ...tool,
                                                actions: tool.actions.map(
                                                  (act, index) => {
                                                    if (
                                                      index === originalIndex
                                                    ) {
                                                      return {
                                                        ...act,
                                                        parameters: {
                                                          ...act.parameters,
                                                          properties: {
                                                            ...act.parameters
                                                              .properties,
                                                            [param[0]]: {
                                                              ...act.parameters
                                                                .properties[
                                                                param[0]
                                                              ],
                                                              value:
                                                                e.target.value,
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
                        </>
                      )}
                    </div>
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
            handleSubmit={async () => {
              if (!validateConfig()) {
                setShowUnsavedModal(false);
                return;
              }
              const configToSave = buildConfigToSave();
              setSaving(true);
              setSaveError('');

              try {
                await userService.updateTool(
                  {
                    id: tool.id,
                    name: tool.name,
                    displayName: tool.displayName,
                    customName: customName,
                    description: tool.description,
                    config: configToSave,
                    actions: 'actions' in tool ? tool.actions : [],
                    status: tool.status,
                  },
                  token,
                );
                setShowUnsavedModal(false);
                handleGoBack();
              } catch {
                setSaveError(t('settings.tools.saveFailed'));
                setShowUnsavedModal(false);
              } finally {
                setSaving(false);
              }
            }}
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
  const [actionToDelete, setActionToDelete] = React.useState<string | null>(
    null,
  );
  const [deleteModalState, setDeleteModalState] =
    React.useState<ActiveState>('INACTIVE');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [expandedActions, setExpandedActions] = React.useState<Set<string>>(
    new Set(),
  );

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

  const handleActionToggle = (actionName: string) => {
    setApiTool((prevApiTool) => {
      const updatedActions = { ...prevApiTool.config.actions };
      const updatedAction = { ...updatedActions[actionName] };
      updatedAction.active = !updatedAction.active;
      updatedActions[actionName] = updatedAction;
      return {
        ...prevApiTool,
        config: { ...prevApiTool.config, actions: updatedActions },
      };
    });
  };

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

      <div className="flex flex-col gap-4">
        {filteredActions.map(([actionName, action], actionIndex) => {
          const isExpanded = expandedActions.has(actionName);
          return (
            <div
              key={actionIndex}
              className="border-border w-full rounded-xl border"
            >
              <div
                className={cn(
                  'border-border bg-muted flex cursor-pointer flex-wrap items-center justify-between px-4 py-3 outline-none',
                  isExpanded ? 'rounded-t-xl border-b' : 'rounded-xl',
                  focusRing,
                )}
                onClick={() => toggleActionExpand(actionName)}
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                onKeyDown={(e) => {
                  if (e.target !== e.currentTarget) return;
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleActionExpand(actionName);
                  }
                }}
              >
                <div className="flex items-center gap-3">
                  <ChevronRight
                    className={cn(
                      'text-muted-foreground size-4 transition-transform duration-200',
                      isExpanded && 'rotate-90',
                    )}
                  />
                  <Badge variant={getMethodBadgeVariant(action.method)}>
                    {action.method}
                  </Badge>
                  <p className="text-foreground font-semibold">{action.name}</p>
                  {action.description && (
                    <p className="text-muted-foreground hidden truncate text-sm md:block md:max-w-xs lg:max-w-md">
                      {action.description}
                    </p>
                  )}
                </div>
                <div
                  className="flex items-center gap-2"
                  onClick={(e) => e.stopPropagation()}
                >
                  <IconButton
                    label={t('convTile.delete')}
                    icon={Trash2}
                    variant="ghost-destructive"
                    size="icon-xs"
                    shape="pill"
                    onClick={() => handleDeleteActionClick(actionName)}
                    className="mr-2"
                  />
                  <div className="flex items-center gap-1">
                    <label
                      htmlFor={`approvalToggle-${actionIndex}`}
                      className="text-muted-foreground text-xs"
                    >
                      {t('settings.tools.requireApproval', 'Approval')}
                    </label>
                    <Switch
                      checked={action.require_approval ?? false}
                      onCheckedChange={() => {
                        setApiTool((prevApiTool) => {
                          const updatedActions = {
                            ...prevApiTool.config.actions,
                          };
                          updatedActions[actionName] = {
                            ...updatedActions[actionName],
                            require_approval:
                              !updatedActions[actionName].require_approval,
                          };
                          return {
                            ...prevApiTool,
                            config: {
                              ...prevApiTool.config,
                              actions: updatedActions,
                            },
                          };
                        });
                      }}
                      id={`approvalToggle-${actionIndex}`}
                    />
                  </div>
                  <Switch
                    checked={action.active}
                    onCheckedChange={() => handleActionToggle(actionName)}
                    id={`actionToggle-${actionIndex}`}
                    aria-label={t('settings.tools.toggleToolAria', {
                      toolName: actionName,
                    })}
                  />
                </div>
              </div>
              {isExpanded && (
                <>
                  <div className="mt-8 px-5">
                    <Input
                      type="text"
                      value={action.url}
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
                      shape="pill"
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
                        <SelectTrigger
                          className="w-full"
                          size="field"
                          shape="pill"
                        >
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
                      shape="pill"
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
                          value={action.body_content_type || 'application/json'}
                          onValueChange={(value) => {
                            setApiTool((prevApiTool) => {
                              const updatedActions = {
                                ...prevApiTool.config.actions,
                              };
                              const updatedAction = {
                                ...updatedActions[actionName],
                              };
                              updatedAction.body_content_type = value as
                                | 'application/json'
                                | 'application/x-www-form-urlencoded'
                                | 'multipart/form-data'
                                | 'text/plain'
                                | 'application/xml'
                                | 'application/octet-stream';
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
                          <SelectTrigger
                            className="w-full"
                            size="field"
                            shape="pill"
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
                </>
              )}
            </div>
          );
        })}
      </div>

      {deleteModalState === 'ACTIVE' && actionToDelete && (
        <ConfirmationModal
          message={t('settings.tools.deleteActionWarning', {
            name: actionToDelete,
          })}
          modalState={deleteModalState}
          setModalState={setDeleteModalState}
          handleSubmit={handleConfirmedDelete}
          handleCancel={() => {
            setDeleteModalState('INACTIVE');
            setActionToDelete(null);
          }}
          submitLabel={t('convTile.delete')}
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
  const idPrefix = React.useId();

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
                  <div className="flex flex-row items-center justify-between gap-2">
                    <Input
                      value={newPropertyKey}
                      size="sm"
                      className="min-w-[130.5px]"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="mt-1">
                      <IconButton
                        label={t('settings.tools.save')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenameProperty}
                        className="mr-1"
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
                    className="min-w-[175.5px]"
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
                <label
                  htmlFor={`${idPrefix}-${section}-${index}-filled-by-llm`}
                  className="ml-2.5 flex cursor-pointer items-start gap-4"
                >
                  <div className="flex items-center">
                    <Checkbox
                      size="sm"
                      id={`${idPrefix}-${section}-${index}-filled-by-llm`}
                      aria-label={t('settings.tools.filledByLLM')}
                      checked={param.filled_by_llm}
                      onCheckedChange={(checked) =>
                        handlePropertyChange(
                          section,
                          key,
                          'filled_by_llm',
                          checked === true,
                        )
                      }
                    />
                  </div>
                </label>
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
                  disabled={param.filled_by_llm}
                  onChange={(e) =>
                    handlePropertyChange(section, key, 'value', e.target.value)
                  }
                  size="sm"
                />
              </TableCell>
              <TableCell width="50px" align="center">
                <IconButton
                  label={t('convTile.delete')}
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
                className="min-w-[130.5px]"
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
            <TableCell width="50px" align="center"></TableCell>
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
            <TableCell width="50px" align="center"></TableCell>
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
                  <div className="flex flex-row items-center justify-between gap-2">
                    <Input
                      value={newPropertyKey}
                      size="sm"
                      className="min-w-[130.5px]"
                      onChange={(e) => setNewPropertyKey(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          handleRenameProperty();
                        }
                      }}
                    />
                    <div className="mt-1">
                      <IconButton
                        label={t('settings.tools.save')}
                        variant="ghost"
                        size="icon-xs"
                        onClick={handleRenameProperty}
                        className="mr-1"
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
                    className="min-w-[175.5px]"
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
                  placeholder={t('settings.tools.headerValuePlaceholder')}
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
              <TableCell width="50px" align="center">
                <IconButton
                  label={t('convTile.delete')}
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
                className="min-w-[130.5px]"
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
            <TableCell width="50px" align="center"></TableCell>
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
            <TableCell width="50px" align="center"></TableCell>
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
                <TableHeader>{t('settings.tools.name')}</TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader width="50px" align="center"></TableHeader>
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
                <TableHeader>{t('settings.tools.name')}</TableHeader>
                <TableHeader>{t('settings.tools.type')}</TableHeader>
                <TableHeader>{t('settings.tools.filledByLLM')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader width="50px" align="center"></TableHeader>
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
                <TableHeader>{t('settings.tools.name')}</TableHeader>
                <TableHeader>{t('settings.tools.type')}</TableHeader>
                <TableHeader>{t('settings.tools.filledByLLM')}</TableHeader>
                <TableHeader>{t('settings.tools.description')}</TableHeader>
                <TableHeader>{t('settings.tools.value')}</TableHeader>
                <TableHeader width="50px" align="center"></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>{renderPropertiesTable('body')}</TableBody>
          </Table>
        </TableContainer>
      </div>
    </div>
  );
}
