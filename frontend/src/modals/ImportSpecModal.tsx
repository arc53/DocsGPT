import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Upload from '../assets/upload.svg';
import Spinner from '../components/Spinner';
import { Button } from '../components/ui/button';
import { Modal } from '../components/ui/modal';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { APIActionType } from '../settings/types';
import { getMethodColorClass } from '../utils/httpMethodColors';

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
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (!selectedFile) return;

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
      contentClassName="max-h-[70vh]"
      footer={
        <>
          <Button
            type="button"
            variant="ghost"
            onClick={handleClose}
            className="rounded-3xl px-5"
          >
            {t('modals.importSpec.cancel')}
          </Button>
          {!parsedResult ? (
            <Button
              type="button"
              onClick={handleParse}
              disabled={!file || loading}
              className="w-20 rounded-3xl px-5 disabled:cursor-not-allowed"
            >
              {loading && <Spinner size="small" />}
              {!loading && t('modals.importSpec.parse')}
            </Button>
          ) : (
            <Button
              type="button"
              onClick={handleImport}
              disabled={selectedActions.size === 0}
              className="rounded-3xl px-5 disabled:cursor-not-allowed"
            >
              {t('modals.importSpec.import', { count: selectedActions.size })}
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {!parsedResult ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {t('modals.importSpec.description')}
            </p>

            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-border dark:border-border hover:border-primary dark:hover:border-primary flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors"
            >
              <img
                src={Upload}
                alt="Upload"
                className="mb-3 h-10 w-10 opacity-60 dark:invert"
              />
              <p className="text-foreground dark:text-foreground text-sm font-medium">
                {file ? file.name : t('modals.importSpec.dropzoneText')}
              </p>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {t('modals.importSpec.supportedFormats')}
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,.yaml,.yml"
                onChange={handleFileChange}
                className="hidden"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 dark:text-red-400">{error}</p>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="bg-muted rounded-xl p-4">
              <h3 className="text-foreground dark:text-foreground font-medium">
                {parsedResult.metadata.title}
              </h3>
              {parsedResult.metadata.description && (
                <p className="mt-1 line-clamp-2 text-sm text-gray-600 dark:text-gray-400">
                  {parsedResult.metadata.description}
                </p>
              )}
              <p className="text-muted-foreground mt-2 text-xs">
                {t('modals.importSpec.version')}:{' '}
                {parsedResult.metadata.version}
              </p>
              <div className="mt-3">
                <label className="mb-1 block text-xs font-medium text-gray-700 dark:text-gray-300">
                  {t('modals.importSpec.baseUrl')}
                </label>
                <input
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  className="border-border dark:border-border text-foreground dark:text-foreground bg-card w-full rounded-lg border px-3 py-2 text-sm outline-hidden"
                  placeholder={
                    parsedResult.metadata.base_url || 'https://api.example.com'
                  }
                />
              </div>
            </div>

            <div className="flex items-center justify-between px-1">
              <p className="text-foreground dark:text-foreground text-sm font-medium">
                {t('modals.importSpec.actionsFound', {
                  count: parsedResult.actions.length,
                })}
              </p>
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={toggleAll}
                className="h-auto p-0"
              >
                {selectedActions.size === parsedResult.actions.length
                  ? t('modals.importSpec.deselectAll')
                  : t('modals.importSpec.selectAll')}
              </Button>
            </div>

            <div className="max-h-72 space-y-2 overflow-y-auto px-1">
              {parsedResult.actions.map((action, index) => (
                <label
                  key={index}
                  className="border-border dark:border-border hover:bg-muted dark:hover:bg-muted flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedActions.has(index)}
                    onChange={() => toggleAction(index)}
                    className="text-primary focus:ring-ring mt-1 h-4 w-4 rounded border-gray-300"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${getMethodColorClass(action.method)}`}
                      >
                        {action.method.toUpperCase()}
                      </span>
                      <span className="text-foreground dark:text-foreground truncate font-medium">
                        {action.name}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-sm text-gray-500 dark:text-gray-400">
                      {action.url}
                    </p>
                    {action.description && (
                      <p className="mt-1 line-clamp-1 text-xs text-gray-400 dark:text-gray-500">
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
