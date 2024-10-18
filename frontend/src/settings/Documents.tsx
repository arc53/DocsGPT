import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useTranslation } from 'react-i18next';
import { useDispatch } from 'react-redux';

import userService from '../api/services/userService';
import SyncIcon from '../assets/sync.svg';
import Trash from '../assets/trash.svg';
import DropdownMenu from '../components/DropdownMenu';
import SkeletonLoader from '../components/SkeletonLoader';
import { Doc, DocumentsProps } from '../models/misc';
import { getDocs } from '../preferences/preferenceApi';
import { setSourceDocs } from '../preferences/preferenceSlice';

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
  const [loading, setLoading] = useState(false);
  const syncOptions = [
    { label: 'Never', value: 'never' },
    { label: 'Daily', value: 'daily' },
    { label: 'Weekly', value: 'weekly' },
    { label: 'Monthly', value: 'monthly' },
  ];

  const handleManageSync = (doc: Doc, sync_frequency: string) => {
    setLoading(true);
    userService
      .manageSync({ source_id: doc.id, sync_frequency })
      .then(() => {
        return getDocs();
      })
      .then((data) => {
        dispatch(setSourceDocs(data));
      })
      .catch((error) => console.error(error))
      .finally(() => {
        setLoading(false);
      });
  };

  return (
    <div className="mt-8">
      <div className="flex flex-col relative">
        <div className="z-10 w-full overflow-x-auto">
          {loading ? (
            <SkeletonLoader count={1} />
          ) : (
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
                {!documents?.length && (
                  <tr>
                    <td colSpan={5} className="!p-4">
                      {t('settings.documents.noData')}
                    </td>
                  </tr>
                )}
                {documents &&
                  documents.map((document, index) => (
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
                              className="h-4 w-4 cursor-pointer hover:opacity-50"
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
          )}
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
