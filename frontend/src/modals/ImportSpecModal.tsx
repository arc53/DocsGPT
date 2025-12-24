import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Upload from '../assets/upload.svg';
import Spinner from '../components/Spinner';
import { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import { APIActionType } from '../settings/types';
import WrapperModal from './WrapperModal';

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

const METHOD_COLORS: Record<string, string> = {
  GET: 'bg-[#D1FAE5] text-[#065F46] dark:bg-[#064E3B]/60 dark:text-[#6EE7B7]',
  POST: 'bg-[#DBEAFE] text-[#1E40AF] dark:bg-[#1E3A8A]/60 dark:text-[#93C5FD]',
  PUT: 'bg-[#FEF3C7] text-[#92400E] dark:bg-[#78350F]/60 dark:text-[#FCD34D]',
  DELETE:
    'bg-[#FEE2E2] text-[#991B1B] dark:bg-[#7F1D1D]/60 dark:text-[#FCA5A5]',
  PATCH: 'bg-[#EDE9FE] text-[#5B21B6] dark:bg-[#4C1D95]/60 dark:text-[#C4B5FD]',
  HEAD: 'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
  OPTIONS:
    'bg-[#F3F4F6] text-[#374151] dark:bg-[#374151]/60 dark:text-[#D1D5DB]',
};

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

  if (modalState !== 'ACTIVE') return null;

  return (
    <WrapperModal
      close={handleClose}
      className="w-full max-w-2xl"
      contentClassName="max-h-[70vh]"
    >
      <div className="flex flex-col gap-4">
        <h2 className="text-jet dark:text-bright-gray text-xl font-semibold">
          {t('modals.importSpec.title')}
        </h2>

        {!parsedResult ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-gray-600 dark:text-gray-400">
              {t('modals.importSpec.description')}
            </p>

            <div
              onClick={() => fileInputRef.current?.click()}
              className="border-silver dark:border-silver/40 hover:border-purple-30 dark:hover:border-purple-30 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-colors"
            >
              <img
                src={Upload}
                alt="Upload"
                className="mb-3 h-10 w-10 opacity-60 dark:invert"
              />
              <p className="text-jet dark:text-bright-gray text-sm font-medium">
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
            <div className="rounded-xl bg-[#F9F9F9] p-4 dark:bg-[#28292D]">
              <h3 className="text-jet dark:text-bright-gray font-medium">
                {parsedResult.metadata.title}
              </h3>
              {parsedResult.metadata.description && (
                <p className="mt-1 line-clamp-2 text-sm text-gray-600 dark:text-gray-400">
                  {parsedResult.metadata.description}
                </p>
              )}
              <p className="mt-2 text-xs text-gray-500">
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
                  className="border-silver dark:border-silver/40 text-jet dark:text-bright-gray w-full rounded-lg border bg-white px-3 py-2 text-sm outline-hidden dark:bg-[#2C2C2C]"
                  placeholder={
                    parsedResult.metadata.base_url || 'https://api.example.com'
                  }
                />
              </div>
            </div>

            <div className="flex items-center justify-between px-1">
              <p className="text-jet dark:text-bright-gray text-sm font-medium">
                {t('modals.importSpec.actionsFound', {
                  count: parsedResult.actions.length,
                })}
              </p>
              <button
                onClick={toggleAll}
                className="text-purple-30 hover:text-violets-are-blue text-sm"
              >
                {selectedActions.size === parsedResult.actions.length
                  ? t('modals.importSpec.deselectAll')
                  : t('modals.importSpec.selectAll')}
              </button>
            </div>

            <div className="max-h-72 space-y-2 overflow-y-auto px-1">
              {parsedResult.actions.map((action, index) => (
                <label
                  key={index}
                  className="border-silver dark:border-silver/40 flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-colors hover:bg-[#F9F9F9] dark:hover:bg-[#28292D]"
                >
                  <input
                    type="checkbox"
                    checked={selectedActions.has(index)}
                    onChange={() => toggleAction(index)}
                    className="text-purple-30 focus:ring-purple-30 mt-1 h-4 w-4 rounded border-gray-300"
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${METHOD_COLORS[action.method.toUpperCase()] || METHOD_COLORS.GET}`}
                      >
                        {action.method.toUpperCase()}
                      </span>
                      <span className="text-jet dark:text-bright-gray truncate font-medium">
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

        <div className="mt-2 flex flex-row-reverse gap-2">
          {!parsedResult ? (
            <button
              onClick={handleParse}
              disabled={!file || loading}
              className="bg-purple-30 hover:bg-violets-are-blue flex w-20 items-center justify-center gap-2 rounded-3xl px-5 py-2 text-sm text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading && <Spinner size="small" color="white" />}
              {!loading && t('modals.importSpec.parse')}
            </button>
          ) : (
            <button
              onClick={handleImport}
              disabled={selectedActions.size === 0}
              className="bg-purple-30 hover:bg-violets-are-blue rounded-3xl px-5 py-2 text-sm text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t('modals.importSpec.import', { count: selectedActions.size })}
            </button>
          )}
          <button
            onClick={handleClose}
            className="dark:text-light-gray cursor-pointer rounded-3xl px-5 py-2 text-sm font-medium hover:bg-gray-100 dark:bg-transparent dark:hover:bg-[#767183]/50"
          >
            {t('modals.importSpec.cancel')}
          </button>
        </div>
      </div>
    </WrapperModal>
  );
}
