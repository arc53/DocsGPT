import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Trash from '../assets/trash.svg';
import SkeletonLoader from '../components/SkeletonLoader';
import { useLoaderState } from '../hooks';
import ConfirmationModal from '../modals/ConfirmationModal';
import CreateAPIKeyModal from '../modals/CreateAPIKeyModal';
import SaveAPIKeyModal from '../modals/SaveAPIKeyModal';
import { selectToken } from '../preferences/preferenceSlice';
import { APIKeyData } from './types';

export default function APIKeys() {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [isCreateModalOpen, setCreateModal] = useState(false);
  const [isSaveKeyModalOpen, setSaveKeyModal] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [apiKeys, setApiKeys] = useState<APIKeyData[]>([]);
  const [loading, setLoading] = useLoaderState(true);
  const [keyToDelete, setKeyToDelete] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const handleFetchKeys = async () => {
    setLoading(true);
    try {
      const response = await userService.getAPIKeys(token);
      if (!response.ok) {
        throw new Error('Failed to fetch API Keys');
      }
      const apiKeys = await response.json();
      setApiKeys(apiKeys);
    } catch (error) {
      console.log(error);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteKey = (id: string) => {
    setLoading(true);
    userService
      .deleteAPIKey({ id }, token)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete API Key');
        }
        return response.json();
      })
      .then((data) => {
        if (data.success === true) {
          setApiKeys((previous) => previous.filter((elem) => elem.id !== id));
        }
        setKeyToDelete(null);
      })
      .catch((error) => {
        console.error(error);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const handleCreateKey = (payload: {
    name: string;
    source?: string;
    retriever?: string;
    prompt_id: string;
    chunks: string;
  }) => {
    setLoading(true);
    userService
      .createAPIKey(payload, token)
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to create API Key');
        }
        return response.json();
      })
      .then((data) => {
        setApiKeys([...apiKeys, data]);
        setCreateModal(false);
        setNewKey(data.key);
        setSaveKeyModal(true);
        handleFetchKeys();
      })
      .catch((error) => {
        console.error(error);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  React.useEffect(() => {
    handleFetchKeys();
  }, []);

  return (
    <div className="mt-8 flex w-full max-w-full flex-col overflow-hidden">
      <div className="relative flex grow flex-col">
        <div className="mb-6">
          <h2 className="text-sonic-silver text-base font-medium">
            {t('settings.apiKeys.description')}
          </h2>
        </div>

        <div className="mb-6 flex flex-col items-start justify-end gap-3 sm:flex-row sm:items-center">
          <button
            onClick={() => setCreateModal(true)}
            className="bg-purple-30 hover:bg-violets-are-blue flex h-[30px] w-[108px] items-center justify-center rounded-full text-sm text-white"
            title={t('settings.apiKeys.createNew')}
          >
            {t('settings.apiKeys.createNew')}
          </button>
        </div>

        <div className="relative w-full">
          <div className="dark:border-silver/40 overflow-hidden rounded-md border border-gray-300">
            <div className="table-scroll overflow-x-auto">
              <table className="w-full table-auto">
                <thead>
                  <tr className="dark:border-silver/40 border-b border-gray-300">
                    <th className="text-sonic-silver w-[35%] px-4 py-3 text-left text-xs font-medium">
                      {t('settings.apiKeys.name')}
                    </th>
                    <th className="text-sonic-silver w-[35%] px-4 py-3 text-left text-xs font-medium">
                      {t('settings.apiKeys.sourceDoc')}
                    </th>
                    <th className="text-sonic-silver w-[25%] px-4 py-3 text-left text-xs font-medium">
                      <span className="hidden sm:inline">
                        {t('settings.apiKeys.key')}
                      </span>
                      <span className="sm:hidden">
                        {t('settings.apiKeys.key')}
                      </span>
                    </th>
                    <th className="w-[5%] px-4 py-3 text-right text-xs font-medium text-gray-700 dark:text-[#E0E0E0]">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="dark:divide-silver/40 divide-y divide-gray-300">
                  {loading ? (
                    <SkeletonLoader component="table" />
                  ) : !apiKeys?.length ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="bg-transparent py-4 text-center text-gray-700 dark:text-neutral-200"
                      >
                        {t('settings.apiKeys.noData')}
                      </td>
                    </tr>
                  ) : (
                    Array.isArray(apiKeys) &&
                    apiKeys.map((element) => (
                      <tr
                        key={element.id}
                        className="group transition-colors hover:bg-gray-50 dark:hover:bg-gray-800/50"
                      >
                        <td className="w-[35%] max-w-0 min-w-48 px-4 py-4 text-sm font-semibold text-gray-700 dark:text-[#E0E0E0]">
                          <div className="truncate" title={element.name}>
                            {element.name}
                          </div>
                        </td>
                        <td className="w-[35%] max-w-0 min-w-48 px-4 py-4 text-sm text-gray-700 dark:text-[#E0E0E0]">
                          <div className="truncate" title={element.source}>
                            {element.source}
                          </div>
                        </td>
                        <td className="w-[25%] px-4 py-4 font-mono text-sm text-gray-700 dark:text-[#E0E0E0]">
                          <div className="truncate" title={element.key}>
                            {element.key}
                          </div>
                        </td>
                        <td className="w-[5%] px-4 py-4 text-right">
                          <div className="flex justify-end">
                            <button
                              onClick={() =>
                                setKeyToDelete({
                                  id: element.id,
                                  name: element.name,
                                })
                              }
                              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-gray-100 dark:hover:bg-gray-700"
                            >
                              <img
                                src={Trash}
                                alt={t('convTile.delete')}
                                className="h-4 w-4 opacity-60 hover:opacity-100"
                              />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
      {isCreateModalOpen && (
        <CreateAPIKeyModal
          createAPIKey={handleCreateKey}
          close={() => setCreateModal(false)}
        />
      )}
      {isSaveKeyModalOpen && (
        <SaveAPIKeyModal apiKey={newKey} close={() => setSaveKeyModal(false)} />
      )}
      {keyToDelete && (
        <ConfirmationModal
          message={t('settings.apiKeys.deleteConfirmation', {
            name: keyToDelete.name,
          })}
          modalState="ACTIVE"
          setModalState={() => setKeyToDelete(null)}
          submitLabel={t('modals.deleteConv.delete')}
          handleSubmit={() => handleDeleteKey(keyToDelete.id)}
          handleCancel={() => setKeyToDelete(null)}
          variant="danger"
        />
      )}
    </div>
  );
}
