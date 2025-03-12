import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import Trash from '../assets/trash.svg';
import CreateAPIKeyModal from '../modals/CreateAPIKeyModal';
import SaveAPIKeyModal from '../modals/SaveAPIKeyModal';
import ConfirmationModal from '../modals/ConfirmationModal';
import { APIKeyData } from './types';
import SkeletonLoader from '../components/SkeletonLoader';
import { useLoaderState } from '../hooks';

export default function APIKeys() {
  const { t } = useTranslation();
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
      const response = await userService.getAPIKeys();
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
      .deleteAPIKey({ id })
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
      .createAPIKey(payload)
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
    <div className="flex flex-col w-full mt-8 max-w-full overflow-hidden">
      <div className="flex flex-col relative flex-grow">
        <div className="mb-6">
          <h2 className="text-base font-medium text-sonic-silver">
            {t('settings.apiKeys.description')}
          </h2>
        </div>

        <div className="mb-6 flex flex-col sm:flex-row justify-end items-start sm:items-center gap-3">
          <button
            onClick={() => setCreateModal(true)}
            className="rounded-full text-sm w-[108px] h-[30px] bg-purple-30 text-white hover:bg-violets-are-blue flex items-center justify-center"
            title={t('settings.apiKeys.createNew')}
          >
            {t('settings.apiKeys.createNew')}
          </button>
        </div>

        <div className="relative w-full">
          <div className="border rounded-md border-gray-300 dark:border-silver/40 overflow-hidden">
            <div className="overflow-x-auto table-scroll">
              <table className="w-full table-auto">
                <thead>
                  <tr className="border-b border-gray-300 dark:border-silver/40">
                    <th className="py-3 px-4 text-left text-xs font-medium text-sonic-silver uppercase w-[35%]">
                      {t('settings.apiKeys.name')}
                    </th>
                    <th className="py-3 px-4 text-left text-xs font-medium text-sonic-silver uppercase w-[35%]">
                      {t('settings.apiKeys.sourceDoc')}
                    </th>
                    <th className="py-3 px-4 text-left text-xs font-medium text-sonic-silver uppercase w-[25%]">
                      <span className="hidden sm:inline">
                        {t('settings.apiKeys.key')}
                      </span>
                      <span className="sm:hidden">
                        {t('settings.apiKeys.key')}
                      </span>
                    </th>
                    <th className="py-3 px-4 text-right text-xs font-medium text-gray-700 dark:text-[#E0E0E0] uppercase w-[5%]">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-300 dark:divide-silver/40">
                  {loading ? (
                    <SkeletonLoader component="table" />
                  ) : !apiKeys?.length ? (
                    <tr>
                      <td
                        colSpan={4}
                        className="py-4 text-center text-gray-700 dark:text-neutral-200 bg-transparent"
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
                        <td className="py-4 px-4 text-sm text-gray-700 dark:text-[#E0E0E0] w-[35%] min-w-48 max-w-0">
                          <div className="truncate" title={element.name}>
                            {element.name}
                          </div>
                        </td>
                        <td className="py-4 px-4 text-sm text-gray-700 dark:text-[#E0E0E0] w-[35%] min-w-48 max-w-0">
                          <div className="truncate" title={element.source}>
                            {element.source}
                          </div>
                        </td>
                        <td className="py-4 px-4 text-sm font-mono text-gray-700 dark:text-[#E0E0E0] w-[25%]">
                          <div className="truncate" title={element.key}>
                            {element.key}
                          </div>
                        </td>
                        <td className="py-4 px-4 text-right w-[5%]">
                          <div className="flex justify-end">
                            <button
                              onClick={() =>
                                setKeyToDelete({
                                  id: element.id,
                                  name: element.name,
                                })
                              }
                              className="inline-flex items-center justify-center w-8 h-8 rounded-full hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors flex-shrink-0"
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
