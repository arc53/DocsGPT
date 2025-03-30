import React from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';

import userService from '../api/services/userService';
import Dropdown from '../components/Dropdown';
import { ActiveState } from '../models/misc';
import ProxiesModal from '../preferences/ProxiesModal';
import { selectToken } from '../preferences/preferenceSlice';

export interface ProxyProps {
  proxies: { name: string; id: string; type: string }[];
  selectedProxy: {
    name: string;
    id: string;
    type: string;
  } | null;
  onSelectProxy: (name: string, id: string, type: string) => void;
  setProxies: React.Dispatch<
    React.SetStateAction<{ name: string; id: string; type: string }[]>
  >;
}

export default function Proxies({
  proxies,
  selectedProxy,
  onSelectProxy,
  setProxies,
}: ProxyProps) {
  const handleSelectProxy = ({
    name,
    id,
    type,
  }: {
    name: string;
    id: string;
    type: string;
  }) => {
    setEditProxyName(name);
    onSelectProxy(name, id, type);
  };
  const token = useSelector(selectToken);
  const [newProxyName, setNewProxyName] = React.useState('');
  const [newProxyConnection, setNewProxyConnection] = React.useState('');
  const [editProxyName, setEditProxyName] = React.useState('');
  const [editProxyConnection, setEditProxyConnection] = React.useState('');
  const [currentProxyEdit, setCurrentProxyEdit] = React.useState({
    id: '',
    name: '',
    type: '',
  });
  const [modalType, setModalType] = React.useState<'ADD' | 'EDIT'>('ADD');
  const [modalState, setModalState] = React.useState<ActiveState>('INACTIVE');
  const { t } = useTranslation();

  const handleAddProxy = async () => {
    try {
      const response = await userService.createProxy(
        {
          name: newProxyName,
          connection: newProxyConnection,
        },
        token,
      );
      if (!response.ok) {
        throw new Error('Failed to add proxy');
      }
      const newProxy = await response.json();
      const newProxyObject = {
        name: newProxyName,
        id: newProxy.id,
        type: 'private',
      };
      console.log(
        'Before selecting new proxy:',
        newProxyName,
        newProxy.id,
        'private',
      );
      if (setProxies) {
        const updatedProxies = [...proxies, newProxyObject];
        setProxies(updatedProxies);
        console.log('Updated proxies list:', updatedProxies);
      }
      setModalState('INACTIVE');
      onSelectProxy(newProxyName, newProxy.id, 'private');
      setNewProxyName('');
      setNewProxyConnection('');
    } catch (error) {
      console.error(error);
      // Fallback to just adding to the local state if API doesn't exist yet
      const newId = `proxy_${Date.now()}`;
      if (setProxies) {
        // Store connection string in localStorage for local fallback
        localStorage.setItem(`proxy_connection_${newId}`, newProxyConnection);
        setProxies([
          ...proxies,
          { name: newProxyName, id: newId, type: 'private' },
        ]);
      }
      setModalState('INACTIVE');
      onSelectProxy(newProxyName, newId, 'private');
      setNewProxyName('');
      setNewProxyConnection('');
    }
  };

  const handleDeleteProxy = (id: string) => {
    // We don't delete the "none" proxy
    if (id === 'none') return;
    userService
      .deleteProxy({ id }, token)
      .then((response) => {
        if (response.ok) {
          // Remove from local state after successful deletion
          setProxies(proxies.filter((proxy) => proxy.id !== id));
          // Also remove any locally stored connection string
          localStorage.removeItem(`proxy_connection_${id}`);
          // If we deleted the currently selected proxy, switch to "None"
          if (selectedProxy && selectedProxy.id === id) {
            onSelectProxy('None', 'none', 'public');
          }
        } else {
          console.warn('Failed to delete proxy');
        }
      })
      .catch((error) => {
        console.error(error);
      });
  };

  const handleFetchProxyConnection = async (id: string) => {
    try {
      // We don't need to fetch connection for the "none" proxy
      if (id === 'none') {
        setEditProxyConnection('');
        return;
      }
      // Check if this is a locally stored proxy (for API fallback)
      const localConnection = localStorage.getItem(`proxy_connection_${id}`);
      if (localConnection) {
        setEditProxyConnection(localConnection);
        return;
      }
      // Otherwise proceed with API call
      const response = await userService.getSingleProxy(id, token);
      if (!response.ok) {
        throw new Error('Failed to fetch proxy connection');
      }
      const proxyData = await response.json();
      setEditProxyConnection(proxyData.connection);
    } catch (error) {
      console.error(error);
      // Set empty string instead of a placeholder
      setEditProxyConnection('');
    }
  };

  const handleSaveChanges = (id: string, type: string) => {
    userService
      .updateProxy(
        {
          id: id,
          name: editProxyName,
          connection: editProxyConnection,
        },
        token,
      )
      .then((response) => {
        if (!response.ok) {
          // If API doesn't exist yet, just handle locally
          console.warn('API not implemented yet');
          // Store connection string in localStorage
          localStorage.setItem(`proxy_connection_${id}`, editProxyConnection);
        }
        if (setProxies) {
          const existingProxyIndex = proxies.findIndex(
            (proxy) => proxy.id === id,
          );
          if (existingProxyIndex === -1) {
            setProxies([
              ...proxies,
              { name: editProxyName, id: id, type: type },
            ]);
          } else {
            const updatedProxies = [...proxies];
            updatedProxies[existingProxyIndex] = {
              name: editProxyName,
              id: id,
              type: type,
            };
            setProxies(updatedProxies);
          }
        }
        setModalState('INACTIVE');
        onSelectProxy(editProxyName, id, type);
      })
      .catch((error) => {
        console.error(error);
        // Handle locally if API fails
        // Store connection string in localStorage
        localStorage.setItem(`proxy_connection_${id}`, editProxyConnection);
        if (setProxies) {
          const existingProxyIndex = proxies.findIndex(
            (proxy) => proxy.id === id,
          );
          if (existingProxyIndex !== -1) {
            const updatedProxies = [...proxies];
            updatedProxies[existingProxyIndex] = {
              name: editProxyName,
              id: id,
              type: type,
            };
            setProxies(updatedProxies);
          }
        }
        setModalState('INACTIVE');
        onSelectProxy(editProxyName, id, type);
      });
  };

  // Split proxies into 'None' and custom proxies
  const customProxies = proxies.filter(
    (p) => p.id !== 'none' && p.name !== 'None',
  );

  // Create options array with None first
  const noneProxy = { name: 'None', id: 'none', type: 'public' };
  const allProxies = [noneProxy, ...customProxies];

  // Ensure valid selectedProxy or default to None
  const finalSelectedProxy =
    selectedProxy && selectedProxy.id !== 'from-url'
      ? selectedProxy
      : noneProxy;

  // Check if the current proxy is the None proxy
  const isNoneSelected =
    !finalSelectedProxy ||
    finalSelectedProxy.id === 'none' ||
    finalSelectedProxy.name === 'None';

  return (
    <>
      <div>
        <div className="flex flex-col gap-4">
          <p className="font-medium dark:text-bright-gray">
            {t('settings.general.proxy')}
          </p>
          <div className="flex flex-row justify-start items-baseline gap-6">
            <Dropdown
              options={allProxies}
              selectedValue={finalSelectedProxy.name}
              placeholder="None"
              onSelect={handleSelectProxy}
              size="w-56"
              rounded="3xl"
              border="border"
              showEdit={!isNoneSelected}
              showDelete={!isNoneSelected}
              onEdit={({
                id,
                name,
                type,
              }: {
                id: string;
                name: string;
                type: string;
              }) => {
                setModalType('EDIT');
                setEditProxyName(name);
                handleFetchProxyConnection(id);
                setCurrentProxyEdit({ id: id, name: name, type: type });
                setModalState('ACTIVE');
              }}
              onDelete={(id: string) => {
                handleDeleteProxy(id);
              }}
            />

            <button
              className="rounded-3xl w-20 h-10 text-sm border border-solid border-violets-are-blue text-violets-are-blue transition-colors hover:text-white hover:bg-violets-are-blue"
              onClick={() => {
                setModalType('ADD');
                setNewProxyName('');
                setNewProxyConnection('');
                setModalState('ACTIVE');
              }}
            >
              {t('settings.general.add')}
            </button>
          </div>
        </div>
      </div>
      {modalState === 'ACTIVE' && (
        <ProxiesModal
          existingProxies={proxies}
          type={modalType}
          modalState={modalState}
          setModalState={setModalState}
          newProxyName={newProxyName}
          setNewProxyName={setNewProxyName}
          newProxyConnection={newProxyConnection}
          setNewProxyConnection={setNewProxyConnection}
          editProxyName={editProxyName}
          setEditProxyName={setEditProxyName}
          editProxyConnection={editProxyConnection}
          setEditProxyConnection={setEditProxyConnection}
          currentProxyEdit={currentProxyEdit}
          handleAddProxy={handleAddProxy}
          handleEditProxy={handleSaveChanges}
        />
      )}
    </>
  );
}
