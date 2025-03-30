import React from 'react';
import { useTranslation } from 'react-i18next';

import Input from '../components/Input';
import WrapperModal from '../modals/WrapperModal';
import { ActiveState } from '../models/misc';

function AddProxy({
  setModalState,
  handleAddProxy,
  newProxyName,
  setNewProxyName,
  newProxyConnection,
  setNewProxyConnection,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleAddProxy?: () => void;
  newProxyName: string;
  setNewProxyName: (name: string) => void;
  newProxyConnection: string;
  setNewProxyConnection: (content: string) => void;
  disableSave: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div>
      <p className="mb-1 text-xl text-jet dark:text-bright-gray">
        {t('modals.proxies.addProxy')}
      </p>
      <p className="mb-7 text-xs text-[#747474] dark:text-[#7F7F82]">
        {t('modals.proxies.addDescription')}
      </p>
      <div>
        <Input
          placeholder={t('modals.proxies.proxyName')}
          type="text"
          className="mb-4"
          value={newProxyName}
          onChange={(e) => setNewProxyName(e.target.value)}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
        />
        <Input
          placeholder={t('modals.proxies.proxyProtocol')}
          type="text"
          className="mb-4 opacity-70 cursor-not-allowed"
          value="HTTP/S"
          onChange={() => {
            /* Protocol field is read-only */
          }}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
          disabled={true}
        />
        <Input
          placeholder={t('modals.proxies.connectionString')}
          type="text"
          className="mb-4"
          value={newProxyConnection}
          onChange={(e) => setNewProxyConnection(e.target.value)}
          labelBgClassName="bg-white dark:bg-[#26272E]"
          borderVariant="thin"
        />
      </div>
      <div className="mt-6 flex flex-row-reverse">
        <button
          onClick={handleAddProxy}
          className="rounded-3xl bg-purple-30 px-5 py-2 text-sm text-white transition-all hover:bg-violets-are-blue disabled:hover:bg-purple-30"
          disabled={disableSave}
          title={
            disableSave && newProxyName ? t('modals.prompts.nameExists') : ''
          }
        >
          {t('modals.prompts.save')}
        </button>
      </div>
    </div>
  );
}

function EditProxy({
  setModalState,
  handleEditProxy,
  editProxyName,
  setEditProxyName,
  editProxyConnection,
  setEditProxyConnection,
  currentProxyEdit,
  disableSave,
}: {
  setModalState: (state: ActiveState) => void;
  handleEditProxy?: (id: string, type: string) => void;
  editProxyName: string;
  setEditProxyName: (name: string) => void;
  editProxyConnection: string;
  setEditProxyConnection: (content: string) => void;
  currentProxyEdit: { name: string; id: string; type: string };
  disableSave: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div>
      <div className="">
        <p className="mb-1 text-xl text-jet dark:text-bright-gray">
          {t('modals.proxies.editProxy')}
        </p>
        <p className="mb-7 text-xs text-[#747474] dark:text-[#7F7F82]">
          {t('modals.proxies.addDescription')}
        </p>
        <div>
          <Input
            placeholder={t('modals.proxies.proxyName')}
            type="text"
            className="mb-4"
            value={editProxyName}
            onChange={(e) => setEditProxyName(e.target.value)}
            labelBgClassName="bg-white dark:bg-charleston-green-2"
            borderVariant="thin"
          />
          <Input
            placeholder={t('modals.proxies.proxyProtocol')}
            type="text"
            className="mb-4 opacity-70 cursor-not-allowed"
            value="HTTP/S"
            onChange={() => {
              /* Protocol field is read-only */
            }}
            labelBgClassName="bg-white dark:bg-charleston-green-2"
            borderVariant="thin"
            disabled={true}
          />
          <Input
            placeholder={t('modals.proxies.connectionString')}
            type="text"
            className="mb-4"
            value={editProxyConnection}
            onChange={(e) => setEditProxyConnection(e.target.value)}
            labelBgClassName="bg-white dark:bg-charleston-green-2"
            borderVariant="thin"
          />
        </div>
        <div className="mt-6 flex flex-row-reverse gap-4">
          <button
            className={`rounded-3xl bg-purple-30 disabled:hover:bg-purple-30 hover:bg-violets-are-blue px-5 py-2 text-sm text-white transition-all ${
              currentProxyEdit.type === 'public'
                ? 'cursor-not-allowed opacity-50'
                : ''
            }`}
            onClick={() => {
              handleEditProxy &&
                handleEditProxy(currentProxyEdit.id, currentProxyEdit.type);
            }}
            disabled={currentProxyEdit.type === 'public' || disableSave}
            title={
              disableSave && editProxyName ? t('modals.prompts.nameExists') : ''
            }
          >
            {t('modals.prompts.save')}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ProxiesModal({
  existingProxies,
  modalState,
  setModalState,
  type,
  newProxyName,
  setNewProxyName,
  newProxyConnection,
  setNewProxyConnection,
  editProxyName,
  setEditProxyName,
  editProxyConnection,
  setEditProxyConnection,
  currentProxyEdit,
  handleAddProxy,
  handleEditProxy,
}: {
  existingProxies: { name: string; id: string; type: string }[];
  modalState: ActiveState;
  setModalState: (state: ActiveState) => void;
  type: 'ADD' | 'EDIT';
  newProxyName: string;
  setNewProxyName: (name: string) => void;
  newProxyConnection: string;
  setNewProxyConnection: (content: string) => void;
  editProxyName: string;
  setEditProxyName: (name: string) => void;
  editProxyConnection: string;
  setEditProxyConnection: (content: string) => void;
  currentProxyEdit: { id: string; name: string; type: string };
  handleAddProxy?: () => void;
  handleEditProxy?: (id: string, type: string) => void;
}) {
  const [disableSave, setDisableSave] = React.useState(true);
  const { t } = useTranslation();

  React.useEffect(() => {
    // Check if fields are filled to enable/disable save button
    if (type === 'ADD') {
      const nameExists = existingProxies.some(
        (proxy) => proxy.name.toLowerCase() === newProxyName.toLowerCase(),
      );
      setDisableSave(
        newProxyName === '' || newProxyConnection === '' || nameExists,
      );
    } else {
      const nameExists = existingProxies.some(
        (proxy) =>
          proxy.name.toLowerCase() === editProxyName.toLowerCase() &&
          proxy.id !== currentProxyEdit.id,
      );
      setDisableSave(
        editProxyName === '' || editProxyConnection === '' || nameExists,
      );
    }
  }, [
    newProxyName,
    newProxyConnection,
    editProxyName,
    editProxyConnection,
    type,
    existingProxies,
    currentProxyEdit,
  ]);

  let view;

  if (type === 'ADD') {
    view = (
      <AddProxy
        setModalState={setModalState}
        handleAddProxy={handleAddProxy}
        newProxyName={newProxyName}
        setNewProxyName={setNewProxyName}
        newProxyConnection={newProxyConnection}
        setNewProxyConnection={setNewProxyConnection}
        disableSave={disableSave}
      />
    );
  } else if (type === 'EDIT') {
    view = (
      <EditProxy
        setModalState={setModalState}
        handleEditProxy={handleEditProxy}
        editProxyName={editProxyName}
        setEditProxyName={setEditProxyName}
        editProxyConnection={editProxyConnection}
        setEditProxyConnection={setEditProxyConnection}
        currentProxyEdit={currentProxyEdit}
        disableSave={disableSave}
      />
    );
  } else {
    view = <></>;
  }

  return modalState === 'ACTIVE' ? (
    <WrapperModal
      close={() => {
        setModalState('INACTIVE');
        if (type === 'ADD') {
          setNewProxyName('');
          setNewProxyConnection('');
        }
      }}
      className="sm:w-[512px] mt-24"
    >
      {view}
    </WrapperModal>
  ) : null;
}
