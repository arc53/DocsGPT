import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import userService from '../api/services/userService';
import SyncIcon from '../assets/sync.svg';
import Trash from '../assets/trash.svg';
import DropdownMenu from '../components/DropdownMenu';
import { Doc, DocumentsProps, ActiveState } from '../models/misc'; // Ensure ActiveState type is imported
import { getDocs } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';
import Input from '../components/Input';
import Upload from '../upload/Upload'; // Import the Upload component

// Utility function to format numbers
const formatTokens = (tokens: number): string => {
  const roundToTwoDecimals = (num: number): string => {
    return (Math.round((num + Number.EPSILON) * 100) / 100).toString();
  };

  if (tokens >= 1_000_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000_000) + 'b';
  } else if (tokens >= 1_000_000) {
    return roundToTwoDecimals(tokens / 1_000_000) + 'm';
  } else if (tokens >= 1_000) {
    return roundToTwoDecimals(tokens / 1_000) + 'k';
  } else {
    return tokens.toString();
  }
};

const Documents: React.FC<DocumentsProps> = ({
  documents,
  handleDeleteDocument,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch();

  // State for search input
  const [searchTerm, setSearchTerm] = useState('');
  // State for modal: active/inactive
  const [modalState, setModalState] = useState<ActiveState>('INACTIVE'); // Initialize with inactive state
  const [isOnboarding, setIsOnboarding] = useState(false); // State for onboarding flag

  const syncOptions = [
    { label: 'Never', value: 'never' },
    { label: 'Daily', value: 'daily' },
    { label: 'Weekly', value: 'weekly' },
    { label: 'Monthly', value: 'monthly' },
  ];

  const handleManageSync = (doc: Doc, sync_frequency: string) => {
    userService
      .manageSync({ source_id: doc.id, sync_frequency })
      .then(() => {
        return getDocs();
      })
      .then((data) => {
        dispatch(setSourceDocs(data));
      })
      .catch((error) => console.error(error));
  };

  // Filter documents based on the search term
  const filteredDocuments = documents?.filter((document) =>
    document.name.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <div className="mt-8">
      <div className="flex flex-col relative">
        <div className="z-10 w-full overflow-x-auto">
          <div className="my-3 flex justify-between items-center ">
            <div className="p-1">
              <Input
                maxLength={256}
                placeholder="Search..."
                name="Document-search-input"
                type="text"
                id="document-search-input"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)} // Handle search input change
              />
            </div>
            <button
              className="rounded-full w-40 bg-purple-30 px-4 py-3 text-white hover:bg-[#6F3FD1]"
              onClick={() => {
                setIsOnboarding(false); // Set onboarding flag if needed
                setModalState('ACTIVE'); // Open the upload modal
              }}
            >
              Add New
            </button>
          </div>
          <table className="table-default">
            <thead>
              <tr>
                <th>{t('settings.documents.name')}</th>
                <th>{t('settings.documents.date')}</th>
                <th>{t('settings.documents.tokenUsage')}</th>
                <th>{t('settings.documents.type')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {!filteredDocuments?.length && (
                <tr>
                  <td colSpan={5} className="!p-4">
                    {t('settings.documents.noData')}
                  </td>
                </tr>
              )}
              {filteredDocuments &&
                filteredDocuments.map((document, index) => (
                  <tr key={index}>
                    <td>{document.name}</td>
                    <td>{document.date}</td>
                    <td>
                      {document.tokens ? formatTokens(+document.tokens) : ''}
                    </td>
                    <td>
                      {document.type === 'remote' ? 'Pre-loaded' : 'Private'}
                    </td>
                    <td>
                      <div className="flex flex-row items-center">
                        {document.type !== 'remote' && (
                          <img
                            src={Trash}
                            alt="Delete"
                            className="h-4 w-4 cursor-pointer opacity-60 hover:opacity-100"
                            id={`img-${index}`}
                            onClick={(event) => {
                              event.stopPropagation();
                              handleDeleteDocument(index, document);
                            }}
                          />
                        )}
                        {document.syncFrequency && (
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
        {/* Conditionally render the Upload modal based on modalState */}
        {modalState === 'ACTIVE' && (
          <Upload
            modalState={modalState}
            setModalState={setModalState}
            isOnboarding={isOnboarding} // Pass the onboarding flag
          />
        )}
      </div>
    </div>
  );
};

Documents.propTypes = {
  documents: PropTypes.array.isRequired,
  handleDeleteDocument: PropTypes.func.isRequired,
};

export default Documents;
