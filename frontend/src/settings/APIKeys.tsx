import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import Trash from '../assets/trash.svg';
import CreateAPIKeyModal from '../modals/CreateAPIKeyModal';
import SaveAPIKeyModal from '../modals/SaveAPIKeyModal';
import { APIKeyData } from './types';
import SkeletonLoader from '../utils/loader';

export default function APIKeys() {
  const { t } = useTranslation();
  const [isCreateModalOpen, setCreateModal] = React.useState(false);
  const [isSaveKeyModalOpen, setSaveKeyModal] = React.useState(false);
  const [newKey, setNewKey] = React.useState('');
  const [apiKeys, setApiKeys] = React.useState<APIKeyData[]>([]);
  const [loading, setLoading] = useState(true);

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
    userService
      .deleteAPIKey({ id })
      .then((response) => {
        if (!response.ok) {
          throw new Error('Failed to delete API Key');
        }
        return response.json();
      })
      .then((data) => {
        data.status === 'ok' &&
          setApiKeys((previous) => previous.filter((elem) => elem.id !== id));
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const handleCreateKey = (payload: {
    name: string;
    source?: string;
    retriever?: string;
    prompt_id: string;
    chunks: string;
  }) => {
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
      });
  };

  React.useEffect(() => {
    handleFetchKeys();
  }, []);

  return (
    <div className="mt-8">
      <div className="flex flex-col max-w-[876px]">
        <div className="flex justify-end">
          <button
            onClick={() => setCreateModal(true)}
            className="rounded-full bg-purple-30 px-4 py-3 text-white hover:bg-[#6F3FD1]"
          >
            {t('settings.apiKeys.createNew')}
          </button>
        </div>
        {isCreateModalOpen && (
          <CreateAPIKeyModal
            createAPIKey={handleCreateKey}
            close={() => setCreateModal(false)}
          />
        )}
        {isSaveKeyModalOpen && (
          <SaveAPIKeyModal
            apiKey={newKey}
            close={() => setSaveKeyModal(false)}
          />
        )}
        <div className="mt-[27px] w-full">
          <div className="w-full overflow-x-auto">
            {loading ? (
              <SkeletonLoader />
            ) : (
              <table className="table-default">
                <thead>
                  <tr>
                    <th>{t('settings.apiKeys.name')}</th>
                    <th>{t('settings.apiKeys.sourceDoc')}</th>
                    <th>{t('settings.apiKeys.key')}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {!apiKeys?.length && (
                    <tr>
                      <td colSpan={4} className="!p-4">
                        {t('settings.apiKeys.noData')}
                      </td>
                    </tr>
                  )}
                  {apiKeys?.map((element, index) => (
                    <tr key={index}>
                      <td>{element.name}</td>
                      <td>{element.source}</td>
                      <td>{element.key}</td>
                      <td>
                        <img
                          src={Trash}
                          alt="Delete"
                          className="h-4 w-4 cursor-pointer hover:opacity-50"
                          id={`img-${index}`}
                          onClick={() => handleDeleteKey(element.id)}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
