import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import useDrivePicker from 'react-google-drive-picker';

import ConnectorAuth from './ConnectorAuth';
import {
  getSessionToken,
  setSessionToken,
  removeSessionToken,
  validateProviderSession,
} from '../utils/providerUtils';
import ConnectedStateSkeleton from './ConnectedStateSkeleton';
import FilesSectionSkeleton from './FileSelectionSkeleton';

interface PickerFile {
  id: string;
  name: string;
  mimeType: string;
  iconUrl: string;
  description?: string;
  sizeBytes?: string;
}

interface GoogleDrivePickerProps {
  token: string | null;
  onSelectionChange: (fileIds: string[], folderIds?: string[]) => void;
}

const GoogleDrivePicker: React.FC<GoogleDrivePickerProps> = ({
  token,
  onSelectionChange,
}) => {
  const { t } = useTranslation();
  const [selectedFiles, setSelectedFiles] = useState<PickerFile[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<PickerFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [authError, setAuthError] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  const [openPicker] = useDrivePicker();

  useEffect(() => {
    const sessionToken = getSessionToken('google_drive');
    if (sessionToken) {
      setIsValidating(true);
      setIsConnected(true); // Optimistically set as connected for skeleton
      validateSession(sessionToken);
    }
  }, [token]);

  const validateSession = async (sessionToken: string) => {
    try {
      const validateResponse = await validateProviderSession(
        token,
        'google_drive',
      );

      if (!validateResponse.ok) {
        setIsConnected(false);
        setAuthError(
          t('modals.uploadDoc.connectors.googleDrive.sessionExpired'),
        );
        setIsValidating(false);
        return false;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(
          validateData.user_email ||
            t('modals.uploadDoc.connectors.auth.connectedUser'),
        );
        setIsConnected(true);
        setAuthError('');
        setAccessToken(validateData.access_token || null);
        setIsValidating(false);
        return true;
      } else {
        setIsConnected(false);
        setAuthError(
          validateData.error ||
            t('modals.uploadDoc.connectors.googleDrive.sessionExpiredGeneric'),
        );
        setIsValidating(false);
        return false;
      }
    } catch (error) {
      console.error('Error validating session:', error);
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.validateFailed'));
      setIsConnected(false);
      setIsValidating(false);
      return false;
    }
  };

  const handleOpenPicker = async () => {
    setIsLoading(true);

    const sessionToken = getSessionToken('google_drive');

    if (!sessionToken) {
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.noSession'));
      setIsLoading(false);
      return;
    }

    if (!accessToken) {
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.noAccessToken'));
      setIsLoading(false);
      return;
    }

    try {
      const clientId: string = import.meta.env.VITE_GOOGLE_CLIENT_ID;

      // Derive appId from clientId (extract numeric part before first dash)
      const appId = clientId ? clientId.split('-')[0] : null;

      if (!clientId || !appId) {
        console.error('Missing Google Drive configuration');

        setIsLoading(false);
        return;
      }

      openPicker({
        clientId: clientId,
        developerKey: '',
        appId: appId,
        setSelectFolderEnabled: false,
        viewId: 'DOCS',
        showUploadView: false,
        showUploadFolders: false,
        supportDrives: false,
        multiselect: true,
        token: accessToken,
        viewMimeTypes:
          'application/vnd.google-apps.document,application/vnd.google-apps.presentation,application/vnd.google-apps.spreadsheet,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/msword,application/vnd.ms-powerpoint,application/vnd.ms-excel,text/plain,text/csv,text/html,text/markdown,text/x-rst,application/json,application/epub+zip,application/rtf,image/jpeg,image/jpg,image/png',
        callbackFunction: (data: any) => {
          setIsLoading(false);
          if (data.action === 'picked') {
            const docs = data.docs;

            const newFiles: PickerFile[] = [];
            const newFolders: PickerFile[] = [];

            docs.forEach((doc: any) => {
              const item = {
                id: doc.id,
                name: doc.name,
                mimeType: doc.mimeType,
                iconUrl: doc.iconUrl || '',
                description: doc.description,
                sizeBytes: doc.sizeBytes,
              };

              if (doc.mimeType === 'application/vnd.google-apps.folder') {
                newFolders.push(item);
              } else {
                newFiles.push(item);
              }
            });

            setSelectedFiles((prevFiles) => {
              const existingFileIds = new Set(prevFiles.map((file) => file.id));
              const uniqueNewFiles = newFiles.filter(
                (file) => !existingFileIds.has(file.id),
              );
              return [...prevFiles, ...uniqueNewFiles];
            });

            setSelectedFolders((prevFolders) => {
              const existingFolderIds = new Set(
                prevFolders.map((folder) => folder.id),
              );
              const uniqueNewFolders = newFolders.filter(
                (folder) => !existingFolderIds.has(folder.id),
              );
              return [...prevFolders, ...uniqueNewFolders];
            });
            onSelectionChange(
              [...selectedFiles, ...newFiles].map((file) => file.id),
              [...selectedFolders, ...newFolders].map((folder) => folder.id),
            );
          }
        },
      });
    } catch (error) {
      console.error('Error opening picker:', error);
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.pickerFailed'));
      setIsLoading(false);
    }
  };

  const handleDisconnect = async () => {
    const sessionToken = getSessionToken('google_drive');
    if (sessionToken) {
      try {
        const apiHost = import.meta.env.VITE_API_HOST;
        await fetch(`${apiHost}/api/connectors/disconnect`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            provider: 'google_drive',
            session_token: sessionToken,
          }),
        });
      } catch (err) {
        console.error('Error disconnecting from Google Drive:', err);
      }
    }

    removeSessionToken('google_drive');
    setIsConnected(false);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setAccessToken(null);
    setUserEmail('');
    setAuthError('');
    onSelectionChange([], []);
  };

  return (
    <div>
      {isValidating ? (
        <>
          <ConnectedStateSkeleton />
          <FilesSectionSkeleton />
        </>
      ) : (
        <>
          <ConnectorAuth
            provider="google_drive"
            label={t('modals.uploadDoc.connectors.googleDrive.connect')}
            onSuccess={(data) => {
              setUserEmail(
                data.user_email ||
                  t('modals.uploadDoc.connectors.auth.connectedUser'),
              );
              setIsConnected(true);
              setAuthError('');

              if (data.session_token) {
                setSessionToken('google_drive', data.session_token);
                validateSession(data.session_token);
              }
            }}
            onError={(error) => {
              setAuthError(error);
              setIsConnected(false);
            }}
            isConnected={isConnected}
            userEmail={userEmail}
            onDisconnect={handleDisconnect}
            errorMessage={authError}
          />

          {isConnected && (
            <div className="rounded-lg border border-[#EEE6FF78] dark:border-[#6A6A6A]">
              <div className="p-4">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-medium">
                    {t('modals.uploadDoc.connectors.googleDrive.selectedFiles')}
                  </h3>
                  <button
                    onClick={() => handleOpenPicker()}
                    className="rounded-md bg-[#A076F6] px-3 py-1 text-sm text-white hover:bg-[#8A5FD4]"
                    disabled={isLoading}
                  >
                    {isLoading
                      ? t('modals.uploadDoc.connectors.googleDrive.loading')
                      : t(
                          'modals.uploadDoc.connectors.googleDrive.selectFiles',
                        )}
                  </button>
                </div>

                {selectedFiles.length === 0 && selectedFolders.length === 0 ? (
                  <p className="text-sm text-gray-600 dark:text-gray-400">
                    {t(
                      'modals.uploadDoc.connectors.googleDrive.noFilesSelected',
                    )}
                  </p>
                ) : (
                  <div className="max-h-60 overflow-y-auto">
                    {selectedFolders.length > 0 && (
                      <div className="mb-2">
                        <h4 className="mb-1 text-xs font-medium text-gray-500">
                          {t('modals.uploadDoc.connectors.googleDrive.folders')}
                        </h4>
                        {selectedFolders.map((folder) => (
                          <div
                            key={folder.id}
                            className="flex items-center border-b border-gray-200 p-2 dark:border-gray-700"
                          >
                            <img
                              src={folder.iconUrl}
                              alt={t(
                                'modals.uploadDoc.connectors.googleDrive.folderAlt',
                              )}
                              className="mr-2 h-5 w-5"
                            />
                            <span className="flex-1 truncate text-sm">
                              {folder.name}
                            </span>
                            <button
                              onClick={() => {
                                const newSelectedFolders =
                                  selectedFolders.filter(
                                    (f) => f.id !== folder.id,
                                  );
                                setSelectedFolders(newSelectedFolders);
                                onSelectionChange(
                                  selectedFiles.map((f) => f.id),
                                  newSelectedFolders.map((f) => f.id),
                                );
                              }}
                              className="ml-2 text-sm text-red-500 hover:text-red-700"
                            >
                              {t(
                                'modals.uploadDoc.connectors.googleDrive.remove',
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {selectedFiles.length > 0 && (
                      <div>
                        <h4 className="mb-1 text-xs font-medium text-gray-500">
                          {t('modals.uploadDoc.connectors.googleDrive.files')}
                        </h4>
                        {selectedFiles.map((file) => (
                          <div
                            key={file.id}
                            className="flex items-center border-b border-gray-200 p-2 dark:border-gray-700"
                          >
                            <img
                              src={file.iconUrl}
                              alt={t(
                                'modals.uploadDoc.connectors.googleDrive.fileAlt',
                              )}
                              className="mr-2 h-5 w-5"
                            />
                            <span className="flex-1 truncate text-sm">
                              {file.name}
                            </span>
                            <button
                              onClick={() => {
                                const newSelectedFiles = selectedFiles.filter(
                                  (f) => f.id !== file.id,
                                );
                                setSelectedFiles(newSelectedFiles);
                                onSelectionChange(
                                  newSelectedFiles.map((f) => f.id),
                                  selectedFolders.map((f) => f.id),
                                );
                              }}
                              className="ml-2 text-sm text-red-500 hover:text-red-700"
                            >
                              {t(
                                'modals.uploadDoc.connectors.googleDrive.remove',
                              )}
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default GoogleDrivePicker;
