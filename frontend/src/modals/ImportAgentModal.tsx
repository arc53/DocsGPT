import { TriangleAlert, CircleCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { type FileRejection } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { Button } from '../components/ui/button';
import { Dropzone } from '../components/ui/dropzone';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { agentEditPath } from '../agents/paths';
import {
  folderPath,
  folderShowsOn,
  formatFolderPath,
} from '../components/folders/folderTree';
import { importFolderRefs } from '../components/folders/importFolderRef';
import { useSourceFolderTree } from '../components/folders/useKnowledgeFolderPicker';
import { ActiveState } from '../models/misc';
import type { ImportModelRefusal } from '../models/types';
import { selectSourceDocs, selectToken } from '../preferences/preferenceSlice';

/** A plan entry for a whole knowledge folder rather than one source. */
const isFolderEntry = (source: { type: string }) => source.type === 'folder';

// Radix Select can't hold an empty value: "Leave unattached" gets a sentinel.
const UNATTACHED = '__docsgpt-unattached__';

/** The map with `key` set to `value`, or without it for "Leave unattached". */
const mapped = (
  map: Record<string, string>,
  key: string,
  value: string,
): Record<string, string> => {
  const next = { ...map };
  if (value === UNATTACHED) delete next[key];
  else next[key] = value;
  return next;
};

// Names come from the file and the account: React escapes them already, so
// i18next must not turn `&` or quotes into entities.
const noEscape = { interpolation: { escapeValue: false } };

const YAML_ACCEPT = {
  'application/x-yaml': ['.yaml', '.yml'],
  'text/yaml': ['.yaml', '.yml'],
};

type PlanSource = {
  name: string;
  /** `folder` for a whole knowledge folder, matched to the importer's own. */
  type: string;
  status: 'matched' | 'missing';
  target_id: string | null;
  /** Folder entries: the entry's key in the file (`folder-N` by default). */
  key?: string;
  /** Folder entries: the names down to it, when the file carries them. */
  path?: string[] | null;
  /** Folder entries: `path` joined with `/`. */
  path_key?: string | null;
};

type PlanTool = {
  key: string;
  type: string;
  name?: string;
  builtin?: boolean;
  status: 'builtin' | 'reuse' | 'create' | 'unavailable';
  target_id?: string | null;
  requires_secrets?: string[];
};

type PlanModel = {
  id?: string;
  display_name?: string;
  status: 'matched' | 'unavailable' | 'reuse' | 'create';
  requires_secrets?: string[];
  /** Why a team import leaves a custom model off. */
  reason?: ImportModelRefusal;
};

type ImportPlan = {
  target: {
    action: 'create' | 'update';
    agent_id: string | null;
    matched_by: string | null;
  };
  sources: PlanSource[];
  tools: PlanTool[];
  prompt: { status: string; name?: string };
  models: PlanModel[];
  /** What the import will leave off (a folder the importer doesn't have). */
  warnings?: string[];
  workflow?: {
    nodes: number;
    edges: number;
    action: 'create' | 'update' | 'delete';
  } | null;
};

interface ImportAgentModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
}

export default function ImportAgentModal({
  modalState,
  setModalState,
}: ImportAgentModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const sourceDocs = useSelector(selectSourceDocs);
  const navigate = useNavigate();

  const [yamlText, setYamlText] = useState<string>('');
  const [fileName, setFileName] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<ImportPlan | null>(null);

  const [sourceMap, setSourceMap] = useState<Record<string, string>>({});
  // A missing folder mapped by hand to a folder of the workspace's tree,
  // keyed the way the server reads `resolution.folders` (its key, else its
  // path, else its name: whichever is the entry's alone).
  const [folderMap, setFolderMap] = useState<Record<string, string>>({});
  const folderRefs = useMemo(() => {
    const entries = (plan?.sources ?? []).filter(isFolderEntry);
    const refs = importFolderRefs(entries);
    return new Map(entries.map((entry, index) => [entry, refs[index]]));
  }, [plan]);
  const { tree: folderTree } = useSourceFolderTree();
  const folderOptions = useMemo(
    () =>
      [...folderTree.byId.values()]
        .filter((folder) => folderShowsOn(folderTree, folder, 'source'))
        .map((folder) => ({
          id: folder.id,
          label: formatFolderPath(folderPath(folderTree, folder.id)),
        }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [folderTree],
  );
  const [toolSecrets, setToolSecrets] = useState<
    Record<string, Record<string, string>>
  >({});
  const [modelKeys, setModelKeys] = useState<Record<string, string>>({});
  const [warnings, setWarnings] = useState<string[] | null>(null);
  const [importedStatus, setImportedStatus] = useState<string | null>(null);
  const [goToEditPath, setGoToEditPath] = useState<string | null>(null);

  const reset = () => {
    setYamlText('');
    setFileName('');
    setLoading(false);
    setImporting(false);
    setError(null);
    setPlan(null);
    setSourceMap({});
    setFolderMap({});
    setToolSecrets({});
    setModelKeys({});
    setWarnings(null);
    setImportedStatus(null);
    setGoToEditPath(null);
  };

  const handleClose = () => {
    setModalState('INACTIVE');
    reset();
  };

  const processFile = async (selectedFile: File) => {
    const name = selectedFile.name.toLowerCase();
    if (!name.endsWith('.yaml') && !name.endsWith('.yml')) {
      setError(t('modals.importAgent.invalidFileType'));
      return;
    }
    setError(null);
    setPlan(null);
    setFileName(selectedFile.name);
    setYamlText(await selectedFile.text());
  };

  const handleDrop = (
    acceptedFiles: File[],
    fileRejections: FileRejection[],
  ) => {
    // A rejected file never reaches acceptedFiles, so without this the
    // drop is a silent no-op and any previously picked file stays staged.
    if (fileRejections.length > 0) {
      setFileName('');
      setYamlText('');
      setError(t('modals.importAgent.invalidFileType'));
      return;
    }
    if (acceptedFiles[0]) processFile(acceptedFiles[0]);
  };

  const handleAnalyze = async () => {
    if (!yamlText) return;
    setLoading(true);
    setError(null);
    try {
      const response = await userService.planImportAgent(yamlText, token);
      const data = await response.json();
      if (!response.ok || !data.success) {
        setError(data.message || t('modals.importAgent.readError'));
        return;
      }
      setPlan(data.plan as ImportPlan);
    } catch {
      setError(t('modals.importAgent.readError'));
    } finally {
      setLoading(false);
    }
  };

  /** A whole-folder entry of the plan: matched, or missing with a picker. */
  const renderFolderEntry = (s: PlanSource, index: number) => {
    const ref = folderRefs.get(s) ?? null;
    // Two folders of one name read apart by their path.
    const name = s.path?.length ? s.path.join(' › ') : s.name;
    return s.status === 'matched' ? (
      <p
        key={`folder:${ref ?? index}`}
        className="flex items-center gap-2 text-sm"
      >
        <CircleCheck className="text-success size-4" aria-hidden="true" />
        {t('modals.importAgent.folderMatched', { name, ...noEscape })}
      </p>
    ) : (
      <div key={`folder:${ref ?? index}`} className="flex flex-col gap-1">
        <p className="flex items-center gap-2 text-sm">
          <TriangleAlert className="text-warning size-4" aria-hidden="true" />
          {t('modals.importAgent.folderMissing', { name, ...noEscape })}
        </p>
        {ref && folderOptions.length > 0 && (
          <FormField
            label={t('modals.importAgent.folderFor', { name, ...noEscape })}
          >
            <Select
              value={folderMap[ref] || ''}
              onValueChange={(value) =>
                setFolderMap((prev) => mapped(prev, ref, value))
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue
                  placeholder={t('modals.importAgent.leaveUnattached')}
                />
              </SelectTrigger>
              <SelectContent>
                {/* A pick can be taken back without cancelling. */}
                <SelectItem value={UNATTACHED}>
                  {t('modals.importAgent.leaveUnattached')}
                </SelectItem>
                {folderOptions.map((folder) => (
                  <SelectItem key={folder.id} value={folder.id}>
                    {folder.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
      </div>
    );
  };

  const handleImport = async () => {
    if (!plan) return;
    setImporting(true);
    setError(null);

    const resolution: {
      sources: Record<string, string>;
      folders: Record<string, string>;
      tools: Record<string, { secrets: Record<string, string> }>;
      models: Record<string, { api_key: string }>;
    } = { sources: {}, folders: {}, tools: {}, models: {} };

    plan.sources.forEach((s) => {
      if (s.status !== 'missing') return;
      if (isFolderEntry(s)) {
        const ref = folderRefs.get(s);
        if (ref && folderMap[ref]) resolution.folders[ref] = folderMap[ref];
      } else if (sourceMap[s.name]) {
        resolution.sources[s.name] = sourceMap[s.name];
      }
    });
    plan.tools.forEach((tool) => {
      if (tool.status === 'create') {
        const secrets = toolSecrets[tool.key] || {};
        if (Object.values(secrets).some((v) => v)) {
          resolution.tools[tool.key] = { secrets };
        }
      }
    });
    plan.models.forEach((model) => {
      if (
        model.status === 'create' &&
        model.display_name &&
        modelKeys[model.display_name]
      ) {
        resolution.models[model.display_name] = {
          api_key: modelKeys[model.display_name],
        };
      }
    });

    try {
      const response = await userService.importAgent(
        { yaml: yamlText, resolution },
        token,
      );
      const data = await response.json();
      if (!response.ok || !data.success) {
        setError(data.message || t('modals.importAgent.importError'));
        return;
      }
      const agentId = data.agent_id as string;
      const editPath =
        data.agent_type === 'workflow'
          ? agentEditPath(agentId, true)
          : agentEditPath(agentId);
      if (data.warnings && data.warnings.length > 0) {
        // Keep the modal open so the user sees what was skipped.
        setGoToEditPath(editPath);
        setWarnings(data.warnings as string[]);
        setImportedStatus((data.status as string) || null);
        setPlan(null);
        return;
      }
      handleClose();
      navigate(editPath);
    } catch {
      setError(t('modals.importAgent.importError'));
    } finally {
      setImporting(false);
    }
  };

  const setToolSecret = (key: string, field: string, value: string) => {
    setToolSecrets((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || {}), [field]: value },
    }));
  };

  const renderFooter = () => {
    if (warnings) {
      return (
        <Button
          type="button"
          onClick={() => {
            const path = goToEditPath;
            handleClose();
            if (path) navigate(path);
          }}
          size="lg"
          shape="pill"
        >
          {t('modals.importAgent.continueToAgent')}
        </Button>
      );
    }
    return (
      <ModalActions
        cancelLabel={t('modals.importAgent.cancel')}
        onCancel={handleClose}
        {...(!plan
          ? {
              submitLabel: t('modals.importAgent.review'),
              onSubmit: handleAnalyze,
              pending: loading,
              disabled: !yamlText,
            }
          : {
              submitLabel: t('modals.importAgent.import'),
              onSubmit: handleImport,
              pending: importing,
            })}
      />
    );
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && handleClose()}
      title={t('modals.importAgent.title')}
      size="lg"
      footer={renderFooter()}
    >
      <div className="flex flex-col gap-4">
        {warnings ? (
          <Alert variant="warning" role="status">
            <AlertTitle>
              {importedStatus === 'published'
                ? t('modals.importAgent.warningsTitlePublished')
                : t('modals.importAgent.warningsTitle')}
            </AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-5">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        ) : !plan ? (
          <div className="flex flex-col gap-4">
            <p className="text-muted-foreground text-sm">
              {t('modals.importAgent.description')}
            </p>
            <Dropzone
              onDrop={handleDrop}
              // The accept map filters drag-and-drop too; processFile's
              // extension check stays as a backstop for odd MIME reports.
              accept={YAML_ACCEPT}
              title={fileName || t('modals.importAgent.dropzoneText')}
              error={error}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <Alert variant="info" role="note">
              <AlertDescription>
                {plan.target.action === 'update'
                  ? t('modals.importAgent.willUpdate', {
                      matchedBy: plan.target.matched_by,
                    })
                  : t('modals.importAgent.willCreate')}
              </AlertDescription>
            </Alert>

            {plan.workflow &&
              (plan.workflow.action === 'delete' ? (
                // Irreversible: the graph, its run history and its artifacts
                // all go. Warn rather than confirming with a green check.
                <Alert variant="warning">
                  <AlertDescription>
                    {t('modals.importAgent.workflowDelete', {
                      nodes: plan.workflow.nodes,
                    })}
                  </AlertDescription>
                </Alert>
              ) : (
                <p className="flex items-center gap-2 text-sm">
                  <CircleCheck
                    className="text-success size-4"
                    aria-hidden="true"
                  />
                  {plan.workflow.action === 'update'
                    ? t('modals.importAgent.workflowUpdate', {
                        nodes: plan.workflow.nodes,
                      })
                    : t('modals.importAgent.workflowCreate', {
                        nodes: plan.workflow.nodes,
                      })}
                </p>
              ))}

            {plan.warnings && plan.warnings.length > 0 && (
              <Alert variant="warning" role="status">
                <AlertTitle>
                  {t('modals.importAgent.planWarningsTitle')}
                </AlertTitle>
                <AlertDescription>
                  <ul className="list-disc space-y-1 pl-5">
                    {plan.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}

            {plan.sources.length > 0 && (
              <Section title={t('modals.importAgent.sources')}>
                {plan.sources.map((s, index) =>
                  isFolderEntry(s) ? (
                    renderFolderEntry(s, index)
                  ) : s.status === 'matched' ? (
                    <p key={s.name} className="flex items-center gap-2 text-sm">
                      <CircleCheck
                        className="text-success size-4"
                        aria-hidden="true"
                      />
                      {t('modals.importAgent.sourceMatched', {
                        name: s.name,
                        ...noEscape,
                      })}
                    </p>
                  ) : (
                    <div key={s.name} className="flex flex-col gap-1">
                      <p className="flex items-center gap-2 text-sm">
                        <TriangleAlert
                          className="text-warning size-4"
                          aria-hidden="true"
                        />
                        {t('modals.importAgent.sourceMissing', {
                          name: s.name,
                          ...noEscape,
                        })}
                      </p>
                      <FormField
                        label={t('modals.importAgent.sourceFor', {
                          name: s.name,
                          ...noEscape,
                        })}
                      >
                        <Select
                          value={sourceMap[s.name] || ''}
                          onValueChange={(value) =>
                            setSourceMap((prev) => mapped(prev, s.name, value))
                          }
                        >
                          <SelectTrigger className="w-full">
                            <SelectValue
                              placeholder={t(
                                'modals.importAgent.leaveUnattached',
                              )}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value={UNATTACHED}>
                              {t('modals.importAgent.leaveUnattached')}
                            </SelectItem>
                            {(sourceDocs || []).map(
                              (doc: { id?: string; name?: string }) => (
                                <SelectItem
                                  key={String(doc.id)}
                                  value={String(doc.id)}
                                >
                                  {doc.name}
                                </SelectItem>
                              ),
                            )}
                          </SelectContent>
                        </Select>
                      </FormField>
                    </div>
                  ),
                )}
              </Section>
            )}

            {plan.tools.length > 0 && (
              <Section title={t('modals.importAgent.tools')}>
                {plan.tools.map((tool) => (
                  <div key={tool.key} className="flex flex-col gap-1">
                    {tool.status === 'builtin' && (
                      <p className="flex items-center gap-2 text-sm">
                        <CircleCheck
                          className="text-success size-4"
                          aria-hidden="true"
                        />
                        {t('modals.importAgent.toolBuiltin', {
                          type: tool.type,
                          ...noEscape,
                        })}
                      </p>
                    )}
                    {tool.status === 'reuse' && (
                      <p className="flex items-center gap-2 text-sm">
                        <CircleCheck
                          className="text-success size-4"
                          aria-hidden="true"
                        />
                        {t('modals.importAgent.toolReuse', {
                          name: tool.name || tool.type,
                          ...noEscape,
                        })}
                      </p>
                    )}
                    {tool.status === 'unavailable' && (
                      <Alert variant="warning">
                        <AlertDescription>
                          {t('modals.importAgent.toolUnavailable', {
                            type: tool.type,
                            ...noEscape,
                          })}
                        </AlertDescription>
                      </Alert>
                    )}
                    {tool.status === 'create' && (
                      <div className="flex flex-col gap-2">
                        <p className="text-sm">
                          {t('modals.importAgent.toolCreate', {
                            name: tool.name || tool.type,
                            ...noEscape,
                          })}
                        </p>
                        {(tool.requires_secrets || []).map((field) => (
                          <Input
                            key={field}
                            type="password"
                            placeholder={t(
                              'modals.importAgent.secretPlaceholder',
                              { field, ...noEscape },
                            )}
                            value={toolSecrets[tool.key]?.[field] || ''}
                            onChange={(e) =>
                              setToolSecret(tool.key, field, e.target.value)
                            }
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </Section>
            )}

            {plan.models.some((m) => m.status === 'create') && (
              <Section title={t('modals.importAgent.models')}>
                {plan.models
                  .filter((m) => m.status === 'create')
                  .map((m) => (
                    <div key={m.display_name} className="flex flex-col gap-1">
                      <p className="text-sm">
                        {t('modals.importAgent.modelCustom', {
                          name: m.display_name,
                          ...noEscape,
                        })}
                      </p>
                      <Input
                        type="password"
                        placeholder={t('modals.importAgent.apiKeyPlaceholder')}
                        value={modelKeys[m.display_name || ''] || ''}
                        onChange={(e) =>
                          setModelKeys((prev) => ({
                            ...prev,
                            [m.display_name || '']: e.target.value,
                          }))
                        }
                      />
                    </div>
                  ))}
              </Section>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-foreground text-sm font-medium">{title}</p>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}
