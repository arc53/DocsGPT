import React from 'react';
import { useDispatch } from 'react-redux';
import { useTranslation } from 'react-i18next';
import PropTypes from 'prop-types';
import { getDocs } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';
import { Doc, DocumentsProps } from '../models/misc';
import { DropdownMenu } from '../components/DropdownMenu';
import TrashIcon from '../assets/trash-red.svg';
import SyncIcon from '../assets/sync.svg';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const Documents: React.FC<DocumentsProps> = ({
  documents,
  handleDeleteDocument,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const syncOptions = [
    { label: 'Never', value: 'none' },
    { label: 'Daily', value: 'daily' },
    { label: 'Weekly', value: 'weekly' },
    { label: 'Monthly', value: 'monthly' },
  ];
  const handleManageSync = (doc: Doc, sync_frequency: string) => {
    const docPath = 'indexes/' + 'local' + '/' + doc.name;
    fetch(
      `${apiHost}/api/manage_sync?path=${docPath}&sync_frequency=${sync_frequency}`,
      {
        method: 'POST',
      },
    )
      .then(() => {
        return getDocs();
      })
      .then((data) => {
        dispatch(setSourceDocs(data));
      })
      .catch((error) => console.error(error));
  };
  return (
    <div className="mt-8">
      <div className="flex flex-col">
        <div className="w-full overflow-x-auto">
          <table className="block w-max table-auto content-center justify-center rounded-xl border text-center dark:border-chinese-silver dark:text-bright-gray">
            <thead>
              <tr>
                <th className="border-r p-4 md:w-[244px]">
                  {t('settings.documents.name')}
                </th>
                <th className="w-[244px] border-r px-4 py-2">
                  {t('settings.documents.date')}
                </th>
                <th className="w-[144px] border-r px-4 py-2">
                  {t('settings.documents.tokenUsage')}
                </th>
                <th className="w-[244px] border-r px-4 py-2">
                  {t('settings.documents.type')}
                </th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {documents &&
                documents.map((document, index) => (
                  <tr key={index}>
                    <td className="border-r border-t px-4 py-2">
                      {document.name}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.date}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.tokens ? document.tokens : ''}
                    </td>
                    <td className="border-r border-t px-4 py-2">
                      {document.location === 'remote'
                        ? 'Pre-loaded'
                        : 'Private'}
                    </td>
                    <td className="border-t px-4 py-2">
                      <div className="flex items-center">
                        {document.location !== 'remote' && (
                          <button
                            className="cursor-pointer rounded-full border border-red-500 border-opacity-40 p-[8px] hover:border-opacity-100"
                            onClick={(event) => {
                              event.stopPropagation();
                              handleDeleteDocument(index, document);
                            }}
                          >
                            <img
                              src={TrashIcon}
                              alt="Delete"
                              className="h-[13px] w-4"
                              id={`img-${index}`}
                            />
                          </button>
                        )}
                        {Object.keys(document.source ? document.source : {})
                          .length !== 0 && (
                          <div className="ml-2">
                            <DropdownMenu
                              name="Sync"
                              options={syncOptions}
                              onSelect={(value: string) => {
                                handleManageSync(document, value);
                              }}
                              defaultValue={document.syncFrequency}
                              icon={SyncIcon}
                            />
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
Documents.propTypes = {
  documents: PropTypes.array.isRequired,
  handleDeleteDocument: PropTypes.func.isRequired,
};
export default Documents;
