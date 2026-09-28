import { ChevronLeft, CircleAlert, FileText } from 'lucide-react';
import { envVar } from '@/env';
import { cn } from '@/lib/utils';
import { useCallback, useEffect, useRef, useState } from 'react';
import { nanoid } from '@reduxjs/toolkit';
import type { FileRejection } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';

import type { RootState } from '../store';
import userService from '../api/services/userService';
import modelService from '../api/services/modelService';
import type { Model } from '../models/types';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { FormField as UiFormField } from '../components/ui/form-field';
import { Label } from '../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Switch } from '../components/ui/switch';
import { Textarea } from '../components/ui/textarea';
import { Modal } from '../components/ui/modal';
import { Separator } from '../components/ui/separator';
import { OptionCard } from '../components/ui/option-card';
import { SectionHeader } from '../components/ui/section-header';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import ConnectorIcon from '../connectors/ConnectorIcon';
import {
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import type { AppDispatch } from '../store';
import { Card } from '../components/ui/card';
import { Dropzone } from '../components/ui/dropzone';
import { ListRow, ListRows } from '../components/ui/list-row';
import { formatBytes } from '../components/artifactViewUtils';
import { ActiveState, Doc } from '../models/misc';

import { getDocs } from '../preferences/preferenceApi';
import {
  selectSelectedDocs,
  selectToken,
  setSelectedDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import {
  CONNECTION_INGESTORS,
  IngestorDefaultConfigs,
  IngestorFormSchemas,
  getIngestorSchema,
  IngestorOption,
  UPLOAD_AND_WEB_INGESTORS,
} from '../upload/types/ingestor';
import { addUploadTask, updateUploadTask } from './uploadSlice';

import { FormField, IngestorConfig, IngestorType } from './types/ingestor';

import { FilePicker } from '../components/FilePicker';
import GoogleDrivePicker from '../components/GoogleDrivePicker';
import { FILE_UPLOAD_ACCEPT } from '../constants/fileUpload';
import RetrievalOptions, {
  DEFAULT_RETRIEVAL_OPTIONS,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from '../settings/components/RetrievalOptions';

/** Per-file limit for local uploads (25 MB), enforced by the dropzone. */
const MAX_UPLOAD_BYTES = 25000000;

function Upload({
  receivedFile = [],
  setModalState,
  isOnboarding,
  renderTab = null,
  close,
  onSuccessfulUpload = () => undefined,
  selectUploadedDoc = true,
  initialIngestor,
}: {
  receivedFile: File[];
  setModalState: (state: ActiveState) => void;
  isOnboarding: boolean;
  renderTab: string | null;
  close: () => void;
  /** Fires once the upload is ingested, with the id of the source it created. */
  onSuccessfulUpload?: (sourceId?: string) => void;
  /**
   * Whether a finished upload also becomes the chat's selected source. Callers
   * that only need the new source's id (the agent builder) pass ``false`` so
   * uploading never repoints the conversation the user left open.
   */
  selectUploadedDoc?: boolean;
  /** Open straight on this source type's form (Connect from a connector card). */
  initialIngestor?: IngestorType;
}) {
  const token = useSelector(selectToken);
  const selectedDocs = useSelector(selectSelectedDocs);
  const connectorCatalog = useSelector(selectConnectorCatalog);
  const connections = useSelector(selectConnections);
  const connectorsLoaded = useSelector(selectConnectorsLoaded);

  const [files, setfiles] = useState<File[]>(receivedFile);
  // Names of the files the last drop turned away (over the size limit or of
  // an unaccepted type), shown under the dropzone.
  const [rejectedFiles, setRejectedFiles] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<boolean>(true);
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [retrievalOptions, setRetrievalOptions] =
    useState<RetrievalOptionsValue>(DEFAULT_RETRIEVAL_OPTIONS);
  const [graphRAGAvailable, setGraphRAGAvailable] = useState(false);
  const [hybridAvailable, setHybridAvailable] = useState(false);
  const [availableModels, setAvailableModels] = useState<Model[]>([]);

  // File picker state
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<string[]>([]);
  // The connection (account) the source syncs from. Pickers report it; S3
  // and Reddit pick it here ('' means "enter new credentials").
  const [connectionId, setConnectionId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    userService
      .getConfig()
      .then((response) => response.json())
      .then((config) => {
        if (!cancelled) {
          setGraphRAGAvailable(!!config?.graphrag_available);
          setHybridAvailable(!!config?.hybrid_available);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Models back the graphrag extraction-model picker; only fetched when the
  // instance supports graphrag.
  useEffect(() => {
    if (!graphRAGAvailable) return;
    let cancelled = false;
    modelService
      .getModels(token)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data)
          setAvailableModels(modelService.transformModels(data.models || []));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [graphRAGAvailable, token]);

  const renderFormFields = () => {
    if (!ingestor.type) return null;
    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) return null;
    const schema: FormField[] = ingestorSchema.fields;

    const generalFields = schema.filter(
      (field: FormField) =>
        !field.advanced && !(usingSavedKeys && credentialKeys.has(field.name)),
    );
    const advancedFields = schema.filter((field: FormField) => field.advanced);

    return (
      <div className="flex flex-col gap-5">
        {keyAccounts.length > 0 && (
          <UiFormField label={t('filePicker.account')}>
            <Select
              value={connectionId ?? 'new'}
              onValueChange={(value) => {
                accountPicked.current = true;
                setConnectionId(value);
              }}
            >
              <SelectTrigger className="w-full" size="field" shape="pill">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {keyAccounts.map((account) => (
                  <SelectItem key={account.id} value={account.id}>
                    {t('settings.connectors.detail.keyEnding', {
                      hint: account.account_label,
                      interpolation: { escapeValue: false },
                    })}
                  </SelectItem>
                ))}
                <SelectItem value="new">
                  {t('modals.uploadDoc.newCredentials')}
                </SelectItem>
              </SelectContent>
            </Select>
          </UiFormField>
        )}
        <div className="flex flex-col gap-5">
          {generalFields.map((field: FormField) => renderField(field))}
        </div>

        {advancedFields.length > 0 && (
          <div
            className={cn(
              'grid transition-[grid-template-rows,opacity] duration-300 ease-out',
              showAdvancedOptions
                ? 'grid-rows-[1fr] opacity-100'
                : 'grid-rows-[0fr] opacity-0',
            )}
          >
            <div className="flex flex-col gap-4 overflow-hidden">
              <Separator className="my-4" />
              <div className="flex flex-col gap-5">
                {advancedFields.map((field: FormField) => renderField(field))}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderField = (field: FormField) => {
    const isRequired = field.required ?? false;
    const fieldLabel = field.labelKey ? t(field.labelKey) : field.label;
    switch (field.type) {
      case 'string':
        return (
          <Input
            key={field.name}
            label={fieldLabel}
            type="text"
            name={field.name}
            value={String(
              ingestor.config[field.name as keyof typeof ingestor.config],
            )}
            onChange={(e) =>
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                e.target.value,
              )
            }
            required={isRequired}
          />
        );
      case 'number':
        return (
          <Input
            key={field.name}
            label={fieldLabel}
            type="number"
            name={field.name}
            value={String(
              ingestor.config[field.name as keyof typeof ingestor.config],
            )}
            onChange={(e) =>
              handleIngestorChange(
                field.name as keyof IngestorConfig['config'],
                Number(e.target.value),
              )
            }
            required={isRequired}
          />
        );
      case 'enum': {
        const currentValue = String(
          ingestor.config[field.name as keyof typeof ingestor.config] ?? '',
        );
        return (
          <UiFormField
            key={field.name}
            label={fieldLabel}
            required={isRequired}
          >
            <Select
              value={currentValue || undefined}
              onValueChange={(value) => {
                handleIngestorChange(
                  field.name as keyof IngestorConfig['config'],
                  value,
                );
              }}
            >
              <SelectTrigger className="w-full" size="field" shape="pill">
                <SelectValue placeholder={fieldLabel} />
              </SelectTrigger>
              <SelectContent>
                {(field.options || []).map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </UiFormField>
        );
      }
      case 'boolean':
        return (
          <div
            key={field.name}
            className="mt-2 flex flex-row items-center gap-3 text-base"
          >
            <Label htmlFor={`field-${field.name}`} className="text-foreground">
              {fieldLabel}
            </Label>
            <Switch
              id={`field-${field.name}`}
              checked={Boolean(
                ingestor.config[field.name as keyof typeof ingestor.config],
              )}
              onCheckedChange={(checked: boolean) => {
                handleIngestorChange(
                  field.name as keyof IngestorConfig['config'],
                  checked,
                );
              }}
            />
          </div>
        );
      case 'textarea':
        return (
          <UiFormField
            key={field.name}
            label={fieldLabel}
            required={isRequired}
          >
            <Textarea
              name={field.name}
              value={String(
                ingestor.config[field.name as keyof typeof ingestor.config] ??
                  '',
              )}
              onChange={(e) =>
                handleIngestorChange(
                  field.name as keyof IngestorConfig['config'],
                  e.target.value,
                )
              }
              required={isRequired}
              rows={8}
              size="lg"
              variant="filled"
            />
          </UiFormField>
        );
      case 'local_file_picker':
        return (
          <div key={field.name} className="flex flex-col gap-3">
            <Dropzone
              onDrop={onDrop}
              multiple
              accept={FILE_UPLOAD_ACCEPT}
              maxSize={MAX_UPLOAD_BYTES}
              title={t('modals.uploadDoc.dropzoneText')}
              description={t('modals.uploadDoc.dropzoneHint')}
              error={
                rejectedFiles.length > 0
                  ? t('modals.uploadDoc.filesRejected', {
                      files: rejectedFiles.join(', '),
                      // React escapes the text; i18next must not do it twice.
                      interpolation: { escapeValue: false },
                    })
                  : undefined
              }
            />
            {files.length > 0 && (
              <Card variant="outline" padding="none">
                <ListRows>
                  {files.map((file) => (
                    <ListRow
                      key={`${file.name}-${file.size}-${file.lastModified}`}
                      leading={
                        <span
                          aria-hidden="true"
                          className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-md"
                        >
                          <FileText className="size-4" />
                        </span>
                      }
                      title={<span title={file.name}>{file.name}</span>}
                      description={formatBytes(file.size)}
                    />
                  ))}
                </ListRows>
              </Card>
            )}
          </div>
        );
      case 'remote_file_picker':
        return (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            onFirstPickName={prefillName}
            onConnectionChange={setConnectionId}
            provider={ingestor.type as unknown as string}
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      case 'google_drive_picker':
        // Google's own picker needs the client id in the browser; without it
        // the server-side file browser lists the same Drive.
        return envVar('VITE_GOOGLE_CLIENT_ID') ? (
          <GoogleDrivePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            onFirstPickName={prefillName}
            onConnectionChange={setConnectionId}
            token={token}
          />
        ) : (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            onFirstPickName={prefillName}
            onConnectionChange={setConnectionId}
            provider="google_drive"
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      case 'share_point_picker':
        return (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            onFirstPickName={prefillName}
            onConnectionChange={setConnectionId}
            provider="share_point"
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      case 'confluence_picker':
        return (
          <FilePicker
            key={field.name}
            onSelectionChange={(
              selectedFileIds: string[],
              selectedFolderIds: string[] = [],
            ) => {
              setSelectedFiles(selectedFileIds);
              setSelectedFolders(selectedFolderIds);
            }}
            onFirstPickName={prefillName}
            onConnectionChange={setConnectionId}
            provider="confluence"
            token={token}
            initialSelectedFiles={selectedFiles}
            initialSelectedFolders={selectedFolders}
          />
        );
      default:
        return null;
    }
  };

  // New unified ingestor state
  const [ingestor, setIngestor] = useState<IngestorConfig>(() => ({
    type: null,
    name: '',
    config: {},
  }));
  const [nameTouched, setNameTouched] = useState(false);

  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const store = useStore<RootState>();

  useEffect(() => {
    if (!connectorsLoaded) dispatch(loadConnectors({ token }));
  }, [connectorsLoaded, dispatch, token]);

  useEffect(() => {
    if (initialIngestor) handleIngestorTypeChange(initialIngestor);
    // Only the type the modal opened with; later picks are the user's.
  }, []);

  /** The name field follows the first picked item until the user edits it. */
  const prefillName = (name: string) => {
    if (nameTouched || !name) return;
    setIngestor((prev) => (prev.name ? prev : { ...prev, name }));
  };

  const connectorFor = (type: IngestorType | null) =>
    type && CONNECTION_INGESTORS.includes(type)
      ? connectorCatalog.find((c) => c.sync_ingestor === type)
      : undefined;
  const selectedConnector = connectorFor(ingestor.type);
  const needsSetup = !!selectedConnector && !selectedConnector.available;
  // S3 and Reddit keep their keys on a connection: once an account is
  // chosen the key fields go away ("enter secrets once").
  const keyAccounts =
    selectedConnector?.auth_kind === 'api_key'
      ? connections.filter(
          (c) =>
            c.connector_key === selectedConnector.key &&
            c.status === 'connected',
        )
      : [];
  const credentialKeys = new Set(
    (selectedConnector?.credential_fields ?? []).map((f) => f.key),
  );
  const usingSavedKeys =
    keyAccounts.length > 0 && !!connectionId && connectionId !== 'new';

  // Default to the first saved account, also when the connections arrive
  // after the modal opened on S3 or Reddit, but never over a choice the
  // user made in the account picker.
  const accountPicked = useRef(false);
  const firstKeyAccount = keyAccounts[0]?.id;
  useEffect(() => {
    accountPicked.current = false;
    setConnectionId(null);
  }, [ingestor.type]);
  useEffect(() => {
    if (selectedConnector?.auth_kind !== 'api_key' || accountPicked.current)
      return;
    setConnectionId(firstKeyAccount ?? 'new');
  }, [ingestor.type, selectedConnector?.auth_kind, firstKeyAccount]);

  const ingestorOptions: IngestorOption[] = IngestorFormSchemas.map(
    (schema) => ({
      label: schema.label,
      value: schema.key,
      icon: schema.icon,
      heading: schema.heading,
    }),
  );

  const resetUploaderState = useCallback(() => {
    setIngestor({ type: null, name: '', config: {} });
    setfiles([]);
    setRejectedFiles([]);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setShowAdvancedOptions(false);
    setRetrievalOptions(DEFAULT_RETRIEVAL_OPTIONS);
    setNameTouched(false);
  }, []);

  const handleTaskFailure = useCallback(
    (clientTaskId: string, errorMessage?: string) => {
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: {
            status: 'failed',
            errorMessage: errorMessage,
          },
        }),
      );
    },
    [dispatch],
  );

  /** Re-read the source list into the store so a new source is pickable. */
  const refreshSourceDocs = useCallback(
    () =>
      getDocs(token).then((docs) => {
        dispatch(setSourceDocs(docs));
        return docs;
      }),
    [dispatch, token],
  );

  /**
   * Finish an upload that never got an ingest task (the wiki source is created
   * synchronously). The list still has to be refreshed, or the caller selects
   * an id no picker can render.
   */
  const finishUntrackedUpload = useCallback(
    (sourceId?: string) => {
      refreshSourceDocs()
        .catch((err) => {
          console.error('Post-upload source-list refresh failed:', err);
        })
        .finally(() => onSuccessfulUpload?.(sourceId));
    },
    [onSuccessfulUpload, refreshSourceDocs],
  );

  /**
   * Wait for the source.ingest.* SSE pipeline to flip this task into a
   * terminal state, then run the post-completion side effects: refresh
   * the global source list, auto-select the new doc, and fire the
   * caller's ``onSuccessfulUpload`` hook. The slice's extraReducer
   * (uploadSlice.ts) is the sole driver of the task's status; we only
   * subscribe so the side effects can fire after the modal has closed.
   */
  const trackTraining = useCallback(
    (clientTaskId: string) => {
      let handled = false;

      const handleTerminal = (
        status: 'completed' | 'failed',
        sourceId?: string,
      ) => {
        if (handled) return;
        handled = true;
        if (status !== 'completed') return;
        refreshSourceDocs()
          .then((docs) => {
            if (selectUploadedDoc && Array.isArray(docs) && sourceId) {
              // Match the id this upload returned. Diffing against the list as
              // it looked before would pick up any source that appeared
              // meanwhile — another upload finishing, or a new team share.
              const newDoc = docs.find((doc: Doc) => doc.id === sourceId);
              if (newDoc) {
                // If only one doc is selected, replace it completely
                // If multiple docs are selected, append the new doc
                if (selectedDocs.length === 1) {
                  dispatch(setSelectedDocs([newDoc]));
                } else {
                  dispatch(setSelectedDocs([...selectedDocs, newDoc]));
                }
              }
            }
            onSuccessfulUpload?.(sourceId);
          })
          .catch((err) => {
            console.error(
              'SSE-driven post-completion source-list refresh failed:',
              err,
            );
          });
      };

      const check = () => {
        const state = store.getState();
        const task = state.upload.tasks.find((t) => t.id === clientTaskId);
        if (!task) return false;
        if (task.status === 'completed' || task.status === 'failed') {
          handleTerminal(task.status, task.sourceId);
          return true;
        }
        // Recover from the race where the terminal SSE landed before
        // ``xhr.onload`` populated ``task.sourceId`` — the slice
        // silently drops such events (no task to match by sourceId).
        // Mirrors ConnectorTree/FileTree's ``recentEvents`` walk.
        if (task.sourceId) {
          for (const event of state.notifications.recentEvents) {
            if (event.scope?.id !== task.sourceId) continue;
            if (event.type === 'source.ingest.completed') {
              handleTerminal('completed', task.sourceId);
              return true;
            }
            if (event.type === 'source.ingest.failed') {
              handleTerminal('failed');
              return true;
            }
          }
        }
        return false;
      };

      if (check()) return;
      const MAX_WAIT_MS = 5 * 60_000;
      let unsubscribe: (() => void) | null = null;
      const timer = window.setTimeout(() => {
        unsubscribe?.();
        if (!handled) {
          handled = true;
          console.warn(
            'trackTraining: timed out waiting for terminal SSE',
            clientTaskId,
          );
          dispatch(
            updateUploadTask({
              id: clientTaskId,
              updates: {
                status: 'failed',
                errorMessage:
                  'Timed out waiting for ingest completion. The ingest may still be running — please refresh to check.',
              },
            }),
          );
        }
      }, MAX_WAIT_MS);
      unsubscribe = store.subscribe(() => {
        if (check()) {
          window.clearTimeout(timer);
          unsubscribe?.();
        }
      });
    },
    [
      dispatch,
      onSuccessfulUpload,
      refreshSourceDocs,
      selectedDocs,
      selectUploadedDoc,
      store,
    ],
  );

  const onDrop = useCallback(
    (acceptedFiles: File[], rejections: FileRejection[] = []) => {
      setfiles(acceptedFiles);
      setRejectedFiles(rejections.map((rejection) => rejection.file.name));
      const pickedName = acceptedFiles[0]?.name;
      if (!nameTouched && pickedName) {
        setIngestor((prev) => ({ ...prev, name: pickedName }));
      }

      // If we're in local_file mode, update the ingestor config
      if (ingestor.type === 'local_file') {
        setIngestor((prevState) => ({
          ...prevState,
          config: {
            ...prevState.config,
            files: acceptedFiles,
          },
        }));
      }
    },
    [ingestor.type, nameTouched],
  );

  const uploadFile = (clientTaskId: string) => {
    const formData = new FormData();
    files.forEach((file) => {
      formData.append('file', file);
    });

    formData.append('name', ingestor.name);
    formData.append('user', 'local');
    formData.append(
      'config',
      JSON.stringify(optionsToConfig(retrievalOptions)),
    );

    const apiHost = envVar('VITE_API_HOST');
    const xhr = new XMLHttpRequest();

    dispatch(
      updateUploadTask({
        id: clientTaskId,
        updates: { status: 'uploading', progress: 0 },
      }),
    );

    xhr.upload.addEventListener('progress', (event) => {
      if (!event.lengthComputable) return;
      const progressPercentage = Number(
        ((event.loaded / event.total) * 100).toFixed(2),
      );
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: { progress: progressPercentage },
        }),
      );
    });

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const parsed = JSON.parse(xhr.responseText) as {
            task_id?: string;
            source_id?: string;
          };
          if (parsed.task_id) {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: {
                  taskId: parsed.task_id,
                  sourceId: parsed.source_id,
                  status: 'training',
                  progress: 0,
                },
              }),
            );
            trackTraining(clientTaskId);
          } else {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: { status: 'completed', progress: 100 },
              }),
            );
            finishUntrackedUpload(parsed.source_id);
          }
        } catch (error) {
          handleTaskFailure(clientTaskId);
        }
      } else {
        handleTaskFailure(clientTaskId, xhr.statusText || undefined);
      }
    };

    xhr.onerror = () => {
      handleTaskFailure(clientTaskId);
    };

    xhr.open('POST', `${apiHost}/api/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Idempotency-Key', clientTaskId);
    xhr.send(formData);
  };

  const uploadRemote = (clientTaskId: string) => {
    if (!ingestor.type) {
      handleTaskFailure(clientTaskId);
      return;
    }

    const formData = new FormData();
    formData.append('name', ingestor.name);
    formData.append('user', 'local');
    formData.append('source', ingestor.type as string);
    formData.append(
      'config',
      JSON.stringify(optionsToConfig(retrievalOptions)),
    );

    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) {
      handleTaskFailure(clientTaskId);
      return;
    }

    const schema: FormField[] = ingestorSchema.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );
    const hasRemoteFilePicker = schema.some(
      (field: FormField) => field.type === 'remote_file_picker',
    );
    const hasGoogleDrivePicker = schema.some(
      (field: FormField) => field.type === 'google_drive_picker',
    );
    const hasSharePointPicker = schema.some(
      (field: FormField) => field.type === 'share_point_picker',
    );
    const hasConfluencePicker = schema.some(
      (field: FormField) => field.type === 'confluence_picker',
    );

    let configData: Record<string, unknown> = { ...ingestor.config };

    if (hasLocalFilePicker) {
      files.forEach((file) => {
        formData.append('file', file);
      });
    } else if (
      hasRemoteFilePicker ||
      hasGoogleDrivePicker ||
      hasSharePointPicker ||
      hasConfluencePicker
    ) {
      configData = {
        provider: ingestor.type as string,
        connection_id: connectionId,
        file_ids: selectedFiles,
        folder_ids: selectedFolders,
      };
    }

    if (usingSavedKeys) {
      configData = Object.fromEntries(
        Object.entries(configData).filter(([key]) => !credentialKeys.has(key)),
      );
      configData.connection_id = connectionId;
    }
    formData.append('data', JSON.stringify(configData));

    const apiHost: string = envVar('VITE_API_HOST');
    const endpoint =
      ingestor.type === 'local_file'
        ? `${apiHost}/api/upload`
        : `${apiHost}/api/remote`;

    const xhr = new XMLHttpRequest();

    dispatch(
      updateUploadTask({
        id: clientTaskId,
        updates: { status: 'uploading', progress: 0 },
      }),
    );

    xhr.upload.addEventListener('progress', (event: ProgressEvent) => {
      if (!event.lengthComputable) return;
      const progressPercentage = Number(
        ((event.loaded / event.total) * 100).toFixed(2),
      );
      dispatch(
        updateUploadTask({
          id: clientTaskId,
          updates: { progress: progressPercentage },
        }),
      );
    });

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText) as {
            task_id?: string;
            source_id?: string;
          };
          if (response.task_id) {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: {
                  taskId: response.task_id,
                  sourceId: response.source_id,
                  status: 'training',
                  progress: 0,
                },
              }),
            );
            trackTraining(clientTaskId);
          } else {
            dispatch(
              updateUploadTask({
                id: clientTaskId,
                updates: { status: 'completed', progress: 100 },
              }),
            );
            finishUntrackedUpload(response.source_id);
          }
        } catch (error) {
          handleTaskFailure(clientTaskId);
        }
      } else {
        handleTaskFailure(clientTaskId, xhr.statusText || undefined);
      }
    };

    xhr.onerror = () => {
      handleTaskFailure(clientTaskId);
    };

    xhr.open('POST', endpoint);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.setRequestHeader('Idempotency-Key', clientTaskId);
    xhr.send(formData);
  };

  const createWiki = (clientTaskId: string) => {
    dispatch(
      updateUploadTask({
        id: clientTaskId,
        updates: { status: 'training', progress: 0 },
      }),
    );
    userService
      .createWiki(
        {
          name: ingestor.name,
          initial_content: String(ingestor.config.initial_content ?? ''),
        },
        token,
      )
      .then((response) => response.json())
      .then((data) => {
        if (!data?.success) {
          handleTaskFailure(clientTaskId, data?.message);
          return;
        }
        dispatch(
          updateUploadTask({
            id: clientTaskId,
            updates: {
              sourceId: data.source_id,
              status: 'completed',
              progress: 100,
            },
          }),
        );
        finishUntrackedUpload(data.source_id);
      })
      .catch(() => handleTaskFailure(clientTaskId));
  };

  const handleClose = useCallback(() => {
    resetUploaderState();
    setModalState('INACTIVE');
    close();
  }, [close, resetUploaderState, setModalState]);

  const handleUpload = () => {
    if (!ingestor.type) return;

    const ingestorSchemaForUpload = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForUpload) return;

    const schema: FormField[] = ingestorSchemaForUpload.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );

    const displayName =
      ingestor.name?.trim() || files[0]?.name || t('modals.uploadDoc.label');

    const clientTaskId = nanoid();

    dispatch(
      addUploadTask({
        id: clientTaskId,
        fileName: displayName,
        progress: 0,
        status: 'preparing',
      }),
    );

    if (ingestor.type === 'wiki') {
      createWiki(clientTaskId);
    } else if (hasLocalFilePicker) {
      uploadFile(clientTaskId);
    } else {
      uploadRemote(clientTaskId);
    }

    handleClose();
  };

  const isUploadDisabled = (): boolean => {
    if (!activeTab) return true;

    if (!ingestor.name?.trim()) {
      return true;
    }

    // Block submit on an incoherent prescreen config; the backend rejects it.
    if (!isPrescreenConfigValid(retrievalOptions)) return true;

    if (!ingestor.type) return true;
    if (needsSetup) return true;
    const ingestorSchemaForValidation = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForValidation) return true;
    const schema: FormField[] = ingestorSchemaForValidation.fields;
    const hasLocalFilePicker = schema.some(
      (field: FormField) => field.type === 'local_file_picker',
    );
    const hasRemoteFilePicker = schema.some(
      (field: FormField) => field.type === 'remote_file_picker',
    );
    const hasGoogleDrivePicker = schema.some(
      (field: FormField) => field.type === 'google_drive_picker',
    );
    const hasSharePointPicker = schema.some(
      (field: FormField) => field.type === 'share_point_picker',
    );
    const hasConfluencePicker = schema.some(
      (field: FormField) => field.type === 'confluence_picker',
    );

    if (hasLocalFilePicker) {
      if (files.length === 0) {
        return true;
      }
    } else if (
      hasRemoteFilePicker ||
      hasGoogleDrivePicker ||
      hasSharePointPicker ||
      hasConfluencePicker
    ) {
      if (selectedFiles.length === 0 && selectedFolders.length === 0) {
        return true;
      }
    }

    const ingestorSchemaForFields = getIngestorSchema(
      ingestor.type as IngestorType,
    );
    if (!ingestorSchemaForFields) return false;
    const formFields: FormField[] = ingestorSchemaForFields.fields;
    for (const field of formFields) {
      if (usingSavedKeys && credentialKeys.has(field.name)) continue;
      if (field.required) {
        // Validate only required fields
        const value =
          ingestor.config[field.name as keyof typeof ingestor.config];

        if (typeof value === 'string' && !value.trim()) {
          return true;
        }

        if (
          typeof value === 'number' &&
          (value === null || value === undefined || value <= 0)
        ) {
          return true;
        }

        if (typeof value === 'boolean' && value === undefined) {
          return true;
        }
      }
    }
    return false;
  };
  const handleIngestorChange = (
    key: keyof IngestorConfig['config'],
    value: string | number | boolean,
  ) => {
    setIngestor((prevState) => ({
      ...prevState,
      config: {
        ...prevState.config,
        [key]: value,
      },
    }));
  };
  const handleIngestorTypeChange = (type: IngestorType | null) => {
    if (type === null) {
      setIngestor({
        type: null,
        name: '',
        config: {},
      });
      setfiles([]);
      setRejectedFiles([]);
      setNameTouched(false);
      return;
    }

    const defaultConfig = IngestorDefaultConfigs[type];
    setIngestor({
      type,
      name: defaultConfig.name,
      config: defaultConfig.config,
    });
    setNameTouched(false);

    // Clear files if switching away from local_file
    if (type !== 'local_file') {
      setfiles([]);
      setRejectedFiles([]);
    }
  };

  const connectionTileState = (type: IngestorType) => {
    const connector = connectorFor(type);
    if (!connector) return undefined;
    if (!connector.available)
      return t('settings.connectors.status.needsAdminSetup');
    const accounts = connections.filter(
      (c) => c.connector_key === connector.key && c.status === 'connected',
    );
    if (accounts.length === 1)
      return t('modals.uploadDoc.tileConnectedAs', {
        account: accounts[0].account_label,
        interpolation: { escapeValue: false },
      });
    if (accounts.length > 1)
      return t('settings.connectors.status.connectedCount', {
        count: accounts.length,
      });
    return t('settings.connectors.status.connect');
  };

  const renderIngestorSelection = () => {
    const optionsFor = (types: IngestorType[]) =>
      types
        .map((type) => ingestorOptions.find((o) => o.value === type))
        .filter((option): option is IngestorOption => !!option);
    return (
      <div className="flex w-full flex-col gap-6">
        <section className="flex flex-col gap-3">
          <SectionHeader
            as="h3"
            size="sm"
            title={t('modals.uploadDoc.groupUploadWeb')}
          />
          <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {optionsFor(UPLOAD_AND_WEB_INGESTORS).map((option) => (
              <OptionCard
                key={option.value}
                icon={
                  <img
                    src={option.icon}
                    alt=""
                    className="size-6 dark:invert"
                  />
                }
                title={t(`modals.uploadDoc.ingestors.${option.value}.label`)}
                onClick={() => handleIngestorTypeChange(option.value)}
              />
            ))}
          </div>
        </section>
        <section className="flex flex-col gap-3">
          <SectionHeader
            as="h3"
            size="sm"
            title={t('modals.uploadDoc.groupConnection')}
          />
          <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
            {optionsFor(CONNECTION_INGESTORS).map((option) => {
              const connector = connectorFor(option.value);
              return (
                <OptionCard
                  key={option.value}
                  icon={
                    <ConnectorIcon
                      icon={connector?.icon ?? option.value}
                      className="size-6"
                    />
                  }
                  title={t(`modals.uploadDoc.ingestors.${option.value}.label`)}
                  description={connectionTileState(option.value)}
                  onClick={() => handleIngestorTypeChange(option.value)}
                />
              );
            })}
          </div>
        </section>
      </div>
    );
  };

  const renderSetupNotice = () =>
    selectedConnector && needsSetup ? (
      <Alert variant="warning">
        <CircleAlert />
        <AlertTitle>
          {t('settings.connectors.status.needsAdminSetup')}
        </AlertTitle>
        <AlertDescription>
          <div className="flex flex-col gap-2">
            {selectedConnector.missing_settings.length > 0 ? (
              <>
                <span>{t('settings.connectors.setupSettings')}</span>
                <code className="font-mono text-xs wrap-anywhere">
                  {selectedConnector.missing_settings.join(', ')}
                </code>
              </>
            ) : (
              <span>{t('settings.connectors.askAdmin')}</span>
            )}
          </div>
        </AlertDescription>
      </Alert>
    ) : null;
  return (
    <Modal
      open={true}
      onOpenChange={(o) => !o && handleClose()}
      hideTitle
      title={t('modals.uploadDoc.label')}
      footer={
        activeTab && ingestor.type ? (
          <Button
            type="button"
            onClick={handleUpload}
            disabled={isUploadDisabled()}
            size="lg"
            shape="pill"
          >
            {ingestor.type === 'wiki'
              ? t('modals.uploadDoc.create')
              : t('modals.uploadDoc.train')}
          </Button>
        ) : undefined
      }
      size="lg"
      mobileVariant="sheet"
    >
      <div className="flex w-full flex-col gap-6">
        {!ingestor.type && (
          <p className="text-foreground text-left text-xl leading-tight font-semibold">
            {t('modals.uploadDoc.selectSource')}
          </p>
        )}

        {activeTab && (
          <>
            {!ingestor.type && renderIngestorSelection()}
            {ingestor.type && (
              <div className="flex flex-col gap-5">
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="sm"
                  onClick={() => handleIngestorTypeChange(null)}
                  className="-ml-3 w-fit justify-start"
                >
                  <ChevronLeft />
                  <span>{t('modals.uploadDoc.back')}</span>
                </Button>

                <h2 className="text-foreground text-xl leading-tight font-semibold">
                  {ingestor.type &&
                    t(`modals.uploadDoc.ingestors.${ingestor.type}.heading`)}
                </h2>

                <Input
                  type="text"
                  value={ingestor.name}
                  onChange={(e) => {
                    setNameTouched(true);
                    setIngestor((prevState) => ({
                      ...prevState,
                      name: e.target.value,
                    }));
                  }}
                  label={t('modals.uploadDoc.name')}
                  required={true}
                  className="w-full"
                />
                {needsSetup ? renderSetupNotice() : renderFormFields()}
                {ingestor.type !== 'wiki' && !needsSetup && (
                  <RetrievalOptions
                    value={retrievalOptions}
                    onChange={setRetrievalOptions}
                    hybridAvailable={hybridAvailable}
                    graphRAGAvailable={graphRAGAvailable}
                    availableModels={availableModels}
                  />
                )}
              </div>
            )}

            {ingestor.type &&
              getIngestorSchema(ingestor.type as IngestorType)?.fields.some(
                (field: FormField) => field.advanced,
              ) && (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
                  className="-ml-3 w-fit justify-start"
                >
                  {showAdvancedOptions
                    ? t('modals.uploadDoc.hideAdvanced')
                    : t('modals.uploadDoc.showAdvanced')}
                </Button>
              )}
          </>
        )}
      </div>
    </Modal>
  );
}

export default Upload;
