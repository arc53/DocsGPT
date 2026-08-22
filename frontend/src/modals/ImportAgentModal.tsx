import { AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import userService from '../api/services/userService';
import Upload from '../assets/upload.svg';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { ActiveState } from '../models/misc';
import { selectSourceDocs, selectToken } from '../preferences/preferenceSlice';

type PlanSource = {
  name: string;
  type: string;
  status: 'matched' | 'missing';
  target_id: string | null;
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
  workflow?: {
    nodes: number;
    edges: number;
    action: 'create' | 'update';
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

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop: (acceptedFiles: File[]) => {
      if (acceptedFiles[0]) processFile(acceptedFiles[0]);
    },
    multiple: false,
    // Declared here (not via getInputProps) so drag-and-drop is filtered
    // too, with drag-over rejection feedback; processFile's extension check
    // stays as a backstop for odd MIME reports.
    accept: {
      'application/x-yaml': ['.yaml', '.yml'],
      'text/yaml': ['.yaml', '.yml'],
    },
  });

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

  const handleImport = async () => {
    if (!plan) return;
    setImporting(true);
    setError(null);

    const resolution: {
      sources: Record<string, string>;
      tools: Record<string, { secrets: Record<string, string> }>;
      models: Record<string, { api_key: string }>;
    } = { sources: {}, tools: {}, models: {} };

    plan.sources.forEach((s) => {
      if (s.status === 'missing' && sourceMap[s.name]) {
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
          ? `/agents/workflow/edit/${agentId}`
          : `/agents/edit/${agentId}`;
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
          className="rounded-3xl px-5"
        >
          {t('modals.importAgent.continueToAgent')}
        </Button>
      );
    }
    return (
      <>
        <Button
          type="button"
          variant="ghost"
          onClick={handleClose}
          className="rounded-3xl px-5"
        >
          {t('modals.importAgent.cancel')}
        </Button>
        {!plan ? (
          <Button
            type="button"
            onClick={handleAnalyze}
            disabled={!yamlText || loading}
            className="w-24 rounded-3xl px-5 disabled:cursor-not-allowed"
          >
            {loading ? (
              <Spinner size="small" />
            ) : (
              t('modals.importAgent.review')
            )}
          </Button>
        ) : (
          <Button
            type="button"
            onClick={handleImport}
            disabled={importing}
            className="rounded-3xl px-5 disabled:cursor-not-allowed"
          >
            {importing ? (
              <Spinner size="small" />
            ) : (
              t('modals.importAgent.import')
            )}
          </Button>
        )}
      </>
    );
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && handleClose()}
      title={t('modals.importAgent.title')}
      size="lg"
      contentClassName="max-h-[70vh]"
      footer={renderFooter()}
    >
      <div className="flex flex-col gap-4">
        {warnings ? (
          <div className="flex flex-col gap-3">
            <p className="text-foreground text-sm">
              {importedStatus === 'published'
                ? t('modals.importAgent.warningsTitlePublished')
                : t('modals.importAgent.warningsTitle')}
            </p>
            <ul className="list-disc space-y-1 pl-5 text-sm text-yellow-700 dark:text-yellow-400">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          </div>
        ) : !plan ? (
          <div className="flex flex-col gap-4">
            <p className="text-muted-foreground text-sm">
              {t('modals.importAgent.description')}
            </p>
            <div
              {...getRootProps({
                className: `border-border hover:border-primary flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors ${
                  isDragActive ? 'border-primary' : ''
                }`,
              })}
            >
              <img
                src={Upload}
                alt=""
                className="mb-3 h-10 w-10 opacity-60 dark:invert"
              />
              <p className="text-foreground text-sm font-medium">
                {fileName || t('modals.importAgent.dropzoneText')}
              </p>
              <input {...getInputProps()} />
            </div>
            {error && <p className="text-destructive text-sm">{error}</p>}
          </div>
        ) : (
          <div className="flex flex-col gap-5">
            <div className="bg-muted rounded-xl p-3 text-sm">
              {plan.target.action === 'update'
                ? t('modals.importAgent.willUpdate', {
                    matchedBy: plan.target.matched_by,
                  })
                : t('modals.importAgent.willCreate')}
            </div>

            {plan.workflow && (
              <p className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                {plan.workflow.action === 'update'
                  ? t('modals.importAgent.workflowUpdate', {
                      nodes: plan.workflow.nodes,
                    })
                  : t('modals.importAgent.workflowCreate', {
                      nodes: plan.workflow.nodes,
                    })}
              </p>
            )}

            {plan.sources.length > 0 && (
              <Section title={t('modals.importAgent.sources')}>
                {plan.sources.map((s) =>
                  s.status === 'matched' ? (
                    <p key={s.name} className="flex items-center gap-2 text-sm">
                      <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                      {t('modals.importAgent.sourceMatched', { name: s.name })}
                    </p>
                  ) : (
                    <div key={s.name} className="flex flex-col gap-1">
                      <p className="flex items-center gap-2 text-sm">
                        <AlertTriangle className="h-4 w-4 text-yellow-600 dark:text-yellow-400" />
                        {t('modals.importAgent.sourceMissing', {
                          name: s.name,
                        })}
                      </p>
                      <Select
                        value={sourceMap[s.name] || ''}
                        onValueChange={(value) =>
                          setSourceMap((prev) => ({ ...prev, [s.name]: value }))
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
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                        {t('modals.importAgent.toolBuiltin', {
                          type: tool.type,
                        })}
                      </p>
                    )}
                    {tool.status === 'reuse' && (
                      <p className="flex items-center gap-2 text-sm">
                        <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
                        {t('modals.importAgent.toolReuse', {
                          name: tool.name || tool.type,
                        })}
                      </p>
                    )}
                    {tool.status === 'unavailable' && (
                      <p className="text-destructive flex items-center gap-2 text-sm">
                        <AlertTriangle className="h-4 w-4" />
                        {t('modals.importAgent.toolUnavailable', {
                          type: tool.type,
                        })}
                      </p>
                    )}
                    {tool.status === 'create' && (
                      <div className="flex flex-col gap-2">
                        <p className="text-sm">
                          {t('modals.importAgent.toolCreate', {
                            name: tool.name || tool.type,
                          })}
                        </p>
                        {(tool.requires_secrets || []).map((field) => (
                          <Input
                            key={field}
                            type="password"
                            placeholder={t(
                              'modals.importAgent.secretPlaceholder',
                              { field },
                            )}
                            value={toolSecrets[tool.key]?.[field] || ''}
                            onChange={(e) =>
                              setToolSecret(tool.key, field, e.target.value)
                            }
                            className="bg-card h-auto rounded-lg px-3 py-2 text-sm md:text-sm"
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
                        className="bg-card h-auto rounded-lg px-3 py-2 text-sm md:text-sm"
                      />
                    </div>
                  ))}
              </Section>
            )}

            {error && <p className="text-destructive text-sm">{error}</p>}
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
