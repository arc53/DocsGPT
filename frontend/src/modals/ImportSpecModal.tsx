import { useState } from 'react';
import { type FileRejection } from 'react-dropzone';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Checkbox } from '../components/ui/checkbox';
import { Dropzone } from '../components/ui/dropzone';
import { FormField } from '../components/ui/form-field';
import { Input } from '../components/ui/input';
import { Modal, ModalActions } from '../components/ui/modal';
import { SectionHeader } from '../components/ui/section-header';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { APIActionType } from '../settings/types';
import { getMethodBadgeVariant } from '../utils/httpMethodColors';

interface ImportSpecModalProps {
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  onImport: (actions: APIActionType[]) => void;
}

interface ParsedResult {
  metadata: {
    title: string;
    description: string;
    version: string;
    base_url: string;
  };
  actions: APIActionType[];
}

export default function ImportSpecModal({
  modalState,
  setModalState,
  onImport,
}: ImportSpecModalProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);

  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parsedResult, setParsedResult] = useState<ParsedResult | null>(null);
  const [selectedActions, setSelectedActions] = useState<Set<number>>(
    new Set(),
  );
  const [baseUrl, setBaseUrl] = useState<string>('');

  const handleClose = () => {
    setModalState('INACTIVE');
    setFile(null);
    setLoading(false);
    setError(null);
    setParsedResult(null);
    setSelectedActions(new Set());
    setBaseUrl('');
  };

  const processFile = (selectedFile: File) => {
    const validExtensions = ['.json', '.yaml', '.yml'];
    const hasValidExtension = validExtensions.some((ext) =>
      selectedFile.name.toLowerCase().endsWith(ext),
    );

    if (!hasValidExtension) {
      setError(t('modals.importSpec.invalidFileType'));
      return;
    }

    setFile(selectedFile);
    setError(null);
    setParsedResult(null);
  };

  const handleDrop = (
    acceptedFiles: File[],
    fileRejections: FileRejection[],
  ) => {
    // A rejected file never reaches acceptedFiles, so without this the
    // drop is a silent no-op and any previously picked file stays staged.
    if (fileRejections.length > 0) {
      setFile(null);
      setParsedResult(null);
      setError(t('modals.importSpec.invalidFileType'));
      return;
    }
    if (acceptedFiles[0]) processFile(acceptedFiles[0]);
  };

  const handleParse = async () => {
    if (!file) return;

    setLoading(true);
    setError(null);

    try {
      const response = await userService.parseSpec(file, token);
      if (!response.ok) {
        const errorData = await response.json();
        setError(
          errorData.error ||
            errorData.message ||
            t('modals.importSpec.parseError'),
        );
        return;
      }

      const result = await response.json();
      if (result.success) {
        setParsedResult(result);
        setBaseUrl(result.metadata.base_url || '');
        setSelectedActions(
          new Set<number>(
            result.actions.map((_: APIActionType, i: number) => i),
          ),
        );
      } else {
        setError(
          result.error || result.message || t('modals.importSpec.parseError'),
        );
      }
    } catch {
      setError(t('modals.importSpec.parseError'));
    } finally {
      setLoading(false);
    }
  };

  const toggleAction = (index: number) => {
    setSelectedActions((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (!parsedResult) return;
    if (selectedActions.size === parsedResult.actions.length) {
      setSelectedActions(new Set());
    } else {
      setSelectedActions(new Set(parsedResult.actions.map((_, i) => i)));
    }
  };

  const handleImport = () => {
    if (!parsedResult) return;
    const actionsToImport = parsedResult.actions
      .filter((_, i) => selectedActions.has(i))
      .map((action) => ({
        ...action,
        url: action.url.replace(parsedResult.metadata.base_url, baseUrl.trim()),
      }));
    onImport(actionsToImport);
    handleClose();
  };

  return (
    <Modal
      open={modalState === 'ACTIVE'}
      onOpenChange={(o) => !o && handleClose()}
      title={t('modals.importSpec.title')}
      size="lg"
      footer={
        !parsedResult ? (
          <ModalActions
            cancelLabel={t('modals.importSpec.cancel')}
            onCancel={handleClose}
            submitLabel={t('modals.importSpec.parse')}
            onSubmit={handleParse}
            pending={loading}
            disabled={!file}
          />
        ) : (
          <ModalActions
            cancelLabel={t('modals.importSpec.cancel')}
            onCancel={handleClose}
            submitLabel={t('modals.importSpec.import', {
              count: selectedActions.size,
            })}
            onSubmit={handleImport}
            disabled={selectedActions.size === 0}
          />
        )
      }
    >
      <div className="flex flex-col gap-4">
        {!parsedResult ? (
          <div className="flex flex-col gap-4">
            <p className="text-muted-foreground text-sm">
              {t('modals.importSpec.description')}
            </p>

            <Dropzone
              onDrop={handleDrop}
              // Declared here so drag-and-drop is filtered too; processFile's
              // extension check stays as a backstop.
              accept={{
                'application/json': ['.json'],
                'application/x-yaml': ['.yaml', '.yml'],
                'text/yaml': ['.yaml', '.yml'],
              }}
              title={file ? file.name : t('modals.importSpec.dropzoneText')}
              description={t('modals.importSpec.supportedFormats')}
              error={error}
            />
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="bg-muted rounded-xl p-4">
              <SectionHeader
                as="h3"
                size="xs"
                title={parsedResult.metadata.title}
              />
              {parsedResult.metadata.description && (
                <p className="text-muted-foreground mt-1 line-clamp-2 text-sm">
                  {parsedResult.metadata.description}
                </p>
              )}
              <p className="text-muted-foreground mt-2 text-xs">
                {t('modals.importSpec.version')}:{' '}
                {parsedResult.metadata.version}
              </p>
              <FormField
                label={t('modals.importSpec.baseUrl')}
                labelSurface="muted"
                className="mt-5"
              >
                <Input
                  type="text"
                  variant="filled"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={
                    parsedResult.metadata.base_url || 'https://api.example.com'
                  }
                />
              </FormField>
            </div>

            <div className="flex items-center justify-between px-1">
              <p className="text-foreground text-sm font-medium">
                {t('modals.importSpec.actionsFound', {
                  count: parsedResult.actions.length,
                })}
              </p>
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={toggleAll}
                className="-my-1.5 -mr-3"
              >
                {selectedActions.size === parsedResult.actions.length
                  ? t('modals.importSpec.deselectAll')
                  : t('modals.importSpec.selectAll')}
              </Button>
            </div>

            <div className="flex max-h-72 flex-col gap-2 overflow-y-auto px-1">
              {parsedResult.actions.map((action, index) => (
                <label
                  key={index}
                  htmlFor={`import-spec-action-${index}`}
                  className="border-border hover:bg-muted flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors"
                >
                  <Checkbox
                    id={`import-spec-action-${index}`}
                    checked={selectedActions.has(index)}
                    onCheckedChange={() => toggleAction(index)}
                    className="mt-1"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={getMethodBadgeVariant(action.method)}>
                        {action.method.toUpperCase()}
                      </Badge>
                      <span className="text-foreground truncate font-medium">
                        {action.name}
                      </span>
                    </div>
                    <p className="text-muted-foreground mt-1 truncate text-sm">
                      {action.url}
                    </p>
                    {action.description && (
                      <p className="text-muted-foreground/70 mt-1 line-clamp-1 text-xs">
                        {action.description}
                      </p>
                    )}
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
