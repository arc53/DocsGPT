import { ArrowRight, FileText } from 'lucide-react';
import { envVar } from '@/env';
import { useCallback, useEffect, useState } from 'react';
import { nanoid } from '@reduxjs/toolkit';
import type { FileRejection } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector, useStore } from 'react-redux';

import type { RootState } from '../store';
import userService from '../api/services/userService';
import { Alert, AlertDescription } from '../components/ui/alert';
import { Avatar } from '../components/ui/avatar';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { FormField as UiFormField } from '../components/ui/form-field';
import { Textarea } from '../components/ui/textarea';
import { Modal } from '../components/ui/modal';
import { OptionCard } from '../components/ui/option-card';
import { SectionHeader } from '../components/ui/section-header';
import ConnectorIcon from '../connectors/ConnectorIcon';
import { syncTargets } from '../connectors/catalogCards';
import useConnectorLauncher from '../connectors/useConnectorLauncher';
import { connectorName } from '../connectors/i18n';
import {
  connectionNeedsSignIn,
  loadConnectors,
  selectConnections,
  selectConnectorCatalog,
  selectConnectorsEnabled,
  selectConnectorsLoaded,
} from '../connectors/connectorsSlice';
import type { AppDispatch } from '../store';
import type { ConnectorDefinition } from '../connectors/types';
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
  IngestorDefaultConfigs,
  IngestorFormSchemas,
  getIngestorSchema,
  IngestorOption,
  UPLOAD_AND_WEB_INGESTORS,
} from '../upload/types/ingestor';
import { addUploadTask, updateUploadTask } from './uploadSlice';

import { FormField, IngestorConfig, IngestorType } from './types/ingestor';

import { FILE_UPLOAD_ACCEPT } from '../constants/fileUpload';
import RetrievalOptions, {
  DEFAULT_RETRIEVAL_OPTIONS,
  isPrescreenConfigValid,
  optionsToConfig,
  type RetrievalOptionsValue,
} from '../settings/components/RetrievalOptions';
import useRetrievalAvailability from '../settings/components/useRetrievalAvailability';

/** Per-file limit for local uploads (25 MB), enforced by the dropzone. */
const MAX_UPLOAD_BYTES = 25000000;
/** Service tiles on the first step: two rows of three. */
const SERVICE_TILE_LIMIT = 6;

function Upload({
  receivedFile = [],
  setModalState,
  isOnboarding,
  renderTab = null,
  close,
  onSuccessfulUpload = () => undefined,
  selectUploadedDoc = true,
  onBrowseConnectors,
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
  /**
   * Opens the Connectors page on the services that sync. Only a caller that
   * loses nothing by leaving (the Knowledge page) passes it; the dialog
   * closes first.
   */
  onBrowseConnectors?: () => void;
}) {
  const token = useSelector(selectToken);
  const selectedDocs = useSelector(selectSelectedDocs);
  const connectorCatalog = useSelector(selectConnectorCatalog);
  const connections = useSelector(selectConnections);
  const connectorsLoaded = useSelector(selectConnectorsLoaded);
  const connectorsEnabled = useSelector(selectConnectorsEnabled);
  // Connecting a service (a "From a service" card, GitHub's private-
  // repository hand-over) goes to the connect wizard, the one flow every
  // entry point uses. This modal steps aside while it runs: a connect closes
  // it too, a cancel brings it back where it was.
  const [handedOver, setHandedOver] = useState(false);
  const { launch, modals: connectModals } = useConnectorLauncher({
    onConnected: () => close(),
    onCancel: () => setHandedOver(false),
  });

  const [files, setfiles] = useState<File[]>(receivedFile);
  // Names of the files the last drop turned away (over the size limit or of
  // an unaccepted type), shown under the dropzone.
  const [rejectedFiles, setRejectedFiles] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<boolean>(true);
  const [retrievalOptions, setRetrievalOptions] =
    useState<RetrievalOptionsValue>(DEFAULT_RETRIEVAL_OPTIONS);
  const { graphRAGAvailable, hybridAvailable, availableModels } =
    useRetrievalAvailability(token);

  const renderFormFields = () => {
    if (!ingestor.type) return null;
    const ingestorSchema = getIngestorSchema(ingestor.type as IngestorType);
    if (!ingestorSchema) return null;
    return (
      <div className="flex flex-col gap-5">
        {ingestorSchema.fields.map((field: FormField) => renderField(field))}
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
                        <Avatar
                          aria-hidden="true"
                          size="sm"
                          shape="square"
                          variant="icon"
                        >
                          <FileText className="size-4" />
                        </Avatar>
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

    formData.append('data', JSON.stringify(ingestor.config));

    const apiHost: string = envVar('VITE_API_HOST');
    // Local files go through uploadFile; everything else is fetched remotely.
    const endpoint = `${apiHost}/api/remote`;

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
    const schema = getIngestorSchema(ingestor.type);
    if (!schema) return true;
    return schema.fields.some((field: FormField) => {
      if (field.type === 'local_file_picker') return files.length === 0;
      if (!field.required) return false;
      const value = ingestor.config[field.name];
      return typeof value === 'string' && !value.trim();
    });
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

  // "From a service": the services that sync into Knowledge, in the
  // Connectors page's order, each opening the connect wizard in place.
  const syncServices = connectorsEnabled ? syncTargets(connectorCatalog) : [];
  // GitHub is listed once, here. Where it cannot be connected it still reads
  // a public repository by URL, so it stays as that form.
  const githubListed = syncServices.some(
    ({ card, target }) => card.key === 'github' || target.key === 'github',
  );

  /** The service's accounts that can sync, and those that need signing in. */
  const accountsOf = (key: string) => {
    const own = connections.filter((c) => c.connector_key === key);
    return {
      connected: own.filter((c) => c.status === 'connected'),
      broken: own.filter(connectionNeedsSignIn),
    };
  };

  /** The short state line under a service's name, when it has one. */
  const serviceStatus = (key: string) => {
    const { connected, broken } = accountsOf(key);
    if (connected.length > 0) return t('settings.connectors.status.connected');
    if (broken.length > 0) return t('settings.connectors.status.reconnect');
    return undefined;
  };

  const openService = (target: ConnectorDefinition) => {
    const { connected, broken } = accountsOf(target.key);
    if (
      connected.length === 0 &&
      broken.length === 0 &&
      target.key === 'github'
    ) {
      // No account: the public repository form, which offers the connect.
      handleIngestorTypeChange('github');
      return;
    }
    setHandedOver(true);
    if (connected.length > 0) {
      // Opened to add knowledge: an account already connected goes straight
      // to what to sync. With several, the wizard asks which one.
      launch(
        target,
        connected.length === 1
          ? {
              mode: 'sync',
              connectionId: connected[0].id,
              purpose: 'knowledge',
            }
          : { mode: 'sync', purpose: 'knowledge' },
      );
    } else if (broken.length > 0) {
      // Repair the account that stopped rather than add a second one.
      launch(target, {
        mode: 'reconnect',
        connectionId: broken[0].id,
        purpose: 'knowledge',
      });
    } else {
      launch(target, { purpose: 'knowledge' });
    }
  };

  // Two rows at most. A service with an account (connected or needing
  // sign-in) is always shown; the rest fill up to the cap, and "Browse all
  // connectors" leads to everything else.
  const serviceRoom = Math.max(
    0,
    SERVICE_TILE_LIMIT -
      (githubListed ? 0 : 1) -
      syncServices.filter(({ target }) => serviceStatus(target.key)).length,
  );
  let unlinkedShown = 0;
  const visibleServices = syncServices.filter(({ target }) => {
    if (serviceStatus(target.key)) return true;
    unlinkedShown += 1;
    return unlinkedShown <= serviceRoom;
  });

  const renderServices = () => (
    <section className="flex flex-col gap-3">
      <SectionHeader
        as="h3"
        size="sm"
        title={t('modals.uploadDoc.fromService')}
      />
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
        {visibleServices.map(({ card, target }) => (
          <OptionCard
            key={card.key}
            icon={<ConnectorIcon icon={card.icon} className="text-current" />}
            title={connectorName(t, card)}
            description={serviceStatus(target.key)}
            onClick={() => openService(target)}
          />
        ))}
        {!githubListed && (
          <OptionCard
            icon={<ConnectorIcon icon="github" className="text-current" />}
            title={t('modals.uploadDoc.ingestors.github.label')}
            onClick={() => handleIngestorTypeChange('github')}
          />
        )}
      </div>
      {onBrowseConnectors && (
        <Button
          type="button"
          variant="link"
          size="inline"
          className="self-start"
          onClick={() => {
            handleClose();
            onBrowseConnectors();
          }}
        >
          {t('settings.connectors.browseAll')}
          <ArrowRight />
        </Button>
      )}
    </section>
  );

  const renderIngestorSelection = () => {
    const options = UPLOAD_AND_WEB_INGESTORS.map((type) =>
      ingestorOptions.find((o) => o.value === type),
    ).filter((option): option is IngestorOption => !!option);
    return (
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
        {options.map((option) => {
          const Icon = option.icon;
          return (
            <OptionCard
              key={option.value}
              icon={Icon ? <Icon /> : null}
              title={t(`modals.uploadDoc.ingestors.${option.value}.label`)}
              onClick={() => handleIngestorTypeChange(option.value)}
            />
          );
        })}
      </div>
    );
  };

  // The GitHub form reads public repositories by URL with no account (it
  // opens only while no account is connected). A private one needs the
  // user's own GitHub connection: hand over to the connect wizard.
  const githubConnector = connectorsEnabled
    ? connectorCatalog.find((c) => c.key === 'github' && c.available)
    : undefined;
  const renderGitHubHandOver = () =>
    githubConnector ? (
      <Alert variant="info" role="note">
        <AlertDescription>
          {t('modals.uploadDoc.github.privateHint')}
        </AlertDescription>
        <div className="mt-2">
          <Button
            type="button"
            size="sm"
            shape="pill"
            variant="outline"
            onClick={() => {
              setHandedOver(true);
              launch(githubConnector, { purpose: 'knowledge' });
            }}
          >
            {t('modals.uploadDoc.github.connect')}
          </Button>
        </div>
      </Alert>
    ) : null;

  if (handedOver) return <>{connectModals}</>;

  return (
    <Modal
      open={true}
      onOpenChange={(o) => !o && handleClose()}
      title={
        ingestor.type
          ? t(`modals.uploadDoc.ingestors.${ingestor.type}.heading`)
          : t('modals.uploadDoc.selectSource')
      }
      onBack={ingestor.type ? () => handleIngestorTypeChange(null) : undefined}
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
    >
      <div className="flex w-full flex-col gap-6">
        {activeTab && (
          <>
            {!ingestor.type && (
              <>
                {renderIngestorSelection()}
                {renderServices()}
              </>
            )}
            {ingestor.type && (
              <div className="flex flex-col gap-5">
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
                {renderFormFields()}
                {ingestor.type === 'github' && renderGitHubHandOver()}
                {ingestor.type !== 'wiki' && (
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
          </>
        )}
      </div>
    </Modal>
  );
}

export default Upload;
