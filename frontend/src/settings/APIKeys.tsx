import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import userService from '../api/services/userService';
import Trash from '../assets/trash.svg';
import CreateAPIKeyModal from '../modals/CreateAPIKeyModal';
import SaveAPIKeyModal from '../modals/SaveAPIKeyModal';
import { APIKeyData } from './types';
import SkeletonLoader from '../components/SkeletonLoader';
import Input from '../components/Input';

export default function APIKeys() {
  const { t } = useTranslation();
  const [isCreateModalOpen, setCreateModal] = React.useState(false);
  const [isSaveKeyModalOpen, setSaveKeyModal] = React.useState(false);
  const [newKey, setNewKey] = React.useState('');
  const [apiKeys, setApiKeys] = React.useState<APIKeyData[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState(''); // Added state for search term
  const [filteredKeys, setFilteredKeys] = useState<APIKeyData[]>([]); // State for filtered API keys


  const handleFetchKeys = async () => {
    setLoading(true);
    try {
      const response = await userService.getAPIKeys();
      if (!response.ok) {
        throw new Error('Failed to fetch API Keys');
      }
      const apiKeys = await response.json();
      setApiKeys(apiKeys);
      setFilteredKeys(apiKeys); // Initialize the filtered keys as the fetched ones
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

        data.success === true &&
          setApiKeys((previous) => previous.filter((elem) => elem.id !== id));
          setFilteredKeys((previous) =>
            previous.filter((elem) => elem.id !== id),
          );
        }
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
        setFilteredKeys([...apiKeys, data]); // Update filtered keys too
        setCreateModal(false);
        setNewKey(data.key);
        setSaveKeyModal(true);
        handleFetchKeys();
      })
      .catch((error) => {
        console.error(error);
      });
  };

  useEffect(() => {
    handleFetchKeys();
  }, []);

  // Filter API keys when the search term changes
  useEffect(() => {
    setFilteredKeys(
      apiKeys.filter(
        (key) =>
          key.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
          key.source?.toLowerCase().includes(searchTerm.toLowerCase()) ||
          key.key.toLowerCase().includes(searchTerm.toLowerCase()),
      ),
    );
  }, [searchTerm, apiKeys]);

  return (
    <div className="mt-8">
      <div className="flex flex-col max-w-[876px]">
        <div className="flex justify-between">
          <div className="p-1">
            <Input
              maxLength={256}
              placeholder="Search..."
              name="APIkey-search-input"
              type="text"
              id="apikey-search-input"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)} // Update search term
            />
          </div>
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
              <SkeletonLoader count={1} component={'chatbot'} />
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
                {!filteredKeys.length && (
                  <tr>
                    <td colSpan={4} className="!p-4">
                      {t('settings.apiKeys.noData')}
                    </td>
                  </tr>
                )}
                {filteredKeys.map((element, index) => (
                  <tr key={index}>
                    <td>{element.name}</td>
                    <td>{element.source}</td>
                    <td>{element.key}</td>
                    <td>
                      <img
                        src={Trash}
                        alt="Delete"
                        className="h-4 w-4 cursor-pointer opacity-60
                        hover:opacity-100"
                        id={`img-${index}`}
                        onClick={() => handleDeleteKey(element.id)}
                      />
                    </td>
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
