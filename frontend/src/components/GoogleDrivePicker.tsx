import { envVar } from '@/env';
import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import drivePickerImport from 'react-google-drive-picker';

// Vite 8 CJS interop returns the namespace object for this lib instead of
// unwrapping `default`; tolerate both shapes.
const useDrivePicker = ((
  drivePickerImport as unknown as { default?: typeof drivePickerImport }
).default ?? drivePickerImport) as typeof drivePickerImport;

import { useDispatch, useSelector } from 'react-redux';

import connectorsService from '../api/services/connectorsService';
import {
  loadConnectors,
  selectConnections,
} from '../connectors/connectorsSlice';
import type { AppDispatch } from '../store';
import ConnectorIcon from '../connectors/ConnectorIcon';
import ConnectorAuth from './ConnectorAuth';
import SkeletonLoader from './SkeletonLoader';
import { Button } from './ui/button';
import { SectionHeader } from './ui/section-header';

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
  /** The Drive connection to pick from; defaults to the first connected one. */
  connectionId?: string | null;
  /** Reports the account the picker uses, so the upload can name it. */
  onConnectionChange?: (connectionId: string | null) => void;
  onSelectionChange: (fileIds: string[], folderIds?: string[]) => void;
  /** Called with the first item's name when the selection goes from empty to one. */
  onFirstPickName?: (name: string) => void;
}

const GoogleDrivePicker: React.FC<GoogleDrivePickerProps> = ({
  token,
  connectionId: controlledConnectionId,
  onConnectionChange,
  onSelectionChange,
  onFirstPickName,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const connections = useSelector(selectConnections);
  const [chosenConnectionId, setChosenConnectionId] = useState<string | null>(
    null,
  );
  const accounts = connections.filter(
    (c) => c.connector_key === 'google_drive' && c.status === 'connected',
  );
  const activeConnectionId =
    controlledConnectionId ??
    (chosenConnectionId && accounts.some((a) => a.id === chosenConnectionId)
      ? chosenConnectionId
      : (accounts[0]?.id ?? null));
  const activeAccount = accounts.find((a) => a.id === activeConnectionId);
  const isConnected = !!activeConnectionId;
  const [selectedFiles, setSelectedFiles] = useState<PickerFile[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<PickerFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [authError, setAuthError] = useState<string>('');
  const [isValidating, setIsValidating] = useState(false);

  const [openPicker] = useDrivePicker();

  useEffect(() => {
    onConnectionChange?.(activeConnectionId);
  }, [activeConnectionId]);

  // The Picker runs in the browser and needs an access token. It is fetched
  // per use and kept in memory only; the refresh token never leaves the server.
  const fetchAccessToken = async (): Promise<string | null> => {
    if (!activeConnectionId) return null;
    setIsValidating(true);
    try {
      const data = await connectorsService.pickerToken(
        activeConnectionId,
        token,
      );
      if (!data?.success) {
        setAuthError(
          t('modals.uploadDoc.connectors.googleDrive.sessionExpired'),
        );
        dispatch(loadConnectors({ token }));
        return null;
      }
      setAuthError('');
      return data.access_token ?? null;
    } catch (error) {
      console.error('Error fetching the picker token:', error);
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.validateFailed'));
      return null;
    } finally {
      setIsValidating(false);
    }
  };

  const handleOpenPicker = async () => {
    setIsLoading(true);

    if (!activeConnectionId) {
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.noSession'));
      setIsLoading(false);
      return;
    }

    const accessToken = await fetchAccessToken();
    if (!accessToken) {
      setAuthError(t('modals.uploadDoc.connectors.googleDrive.noAccessToken'));
      setIsLoading(false);
      return;
    }

    try {
      const clientId: string = envVar('VITE_GOOGLE_CLIENT_ID');
      const developerKey: string = envVar('VITE_GOOGLE_PICKER_API_KEY') ?? '';

      // Derive appId from clientId (extract numeric part before first dash)
      const appId = clientId ? clientId.split('-')[0] : null;

      if (!clientId || !appId) {
        console.error('Missing Google Drive configuration');

        setIsLoading(false);
        return;
      }

      openPicker({
        clientId: clientId,
        developerKey,
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
            if (
              selectedFiles.length === 0 &&
              selectedFolders.length === 0 &&
              docs.length > 0
            ) {
              onFirstPickName?.(docs[0].name);
            }
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
    if (activeConnectionId) {
      try {
        await connectorsService.disconnect(activeConnectionId, token);
      } catch (err) {
        console.error('Error disconnecting from Google Drive:', err);
      }
      dispatch(loadConnectors({ token }));
    }
    setChosenConnectionId(null);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setAuthError('');
    onSelectionChange([], []);
  };

  return (
    <div>
      {isValidating ? (
        <>
          <SkeletonLoader component="connectedState" />
          <SkeletonLoader component="filesSection" />
        </>
      ) : (
        <>
          <ConnectorAuth
            provider="google_drive"
            label={t('modals.uploadDoc.connectors.googleDrive.connect')}
            icon={<ConnectorIcon icon="drive" className="size-5" />}
            onSuccess={(data) => {
              setAuthError('');
              dispatch(loadConnectors({ token }));
              if (data.connection_id) setChosenConnectionId(data.connection_id);
            }}
            onError={(error) => {
              setAuthError(error);
            }}
            isConnected={isConnected}
            userEmail={
              activeAccount?.account_label ||
              t('modals.uploadDoc.connectors.auth.connectedUser')
            }
            onDisconnect={handleDisconnect}
            errorMessage={authError}
          />

          {isConnected && (
            <div className="border-border rounded-lg border">
              <div className="p-4">
                <div className="mb-4 flex items-center justify-between">
                  <SectionHeader
                    as="h3"
                    size="xs"
                    title={t(
                      'modals.uploadDoc.connectors.googleDrive.selectedFiles',
                    )}
                  />
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => handleOpenPicker()}
                    loading={isLoading}
                  >
                    {t('modals.uploadDoc.connectors.googleDrive.selectFiles')}
                  </Button>
                </div>

                {selectedFiles.length === 0 && selectedFolders.length === 0 ? (
                  <p className="text-muted-foreground text-sm">
                    {t(
                      'modals.uploadDoc.connectors.googleDrive.noFilesSelected',
                    )}
                  </p>
                ) : (
                  <div className="max-h-60 overflow-y-auto">
                    {selectedFolders.length > 0 && (
                      <div className="mb-2 flex flex-col gap-1">
                        <SectionHeader
                          as="h4"
                          size="xs"
                          title={t(
                            'modals.uploadDoc.connectors.googleDrive.folders',
                          )}
                        />
                        {selectedFolders.map((folder) => (
                          <div
                            key={folder.id}
                            className="border-border flex items-center gap-2 border-b p-2"
                          >
                            <img
                              src={folder.iconUrl}
                              alt={t(
                                'modals.uploadDoc.connectors.googleDrive.folderAlt',
                              )}
                              className="size-5"
                            />
                            <span className="flex-1 truncate text-sm">
                              {folder.name}
                            </span>
                            <Button
                              type="button"
                              variant="ghost-destructive"
                              size="xs"
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
                            >
                              {t(
                                'modals.uploadDoc.connectors.googleDrive.remove',
                              )}
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}

                    {selectedFiles.length > 0 && (
                      <div className="flex flex-col gap-1">
                        <SectionHeader
                          as="h4"
                          size="xs"
                          title={t(
                            'modals.uploadDoc.connectors.googleDrive.files',
                          )}
                        />
                        {selectedFiles.map((file) => (
                          <div
                            key={file.id}
                            className="border-border flex items-center gap-2 border-b p-2"
                          >
                            <img
                              src={file.iconUrl}
                              alt={t(
                                'modals.uploadDoc.connectors.googleDrive.fileAlt',
                              )}
                              className="size-5"
                            />
                            <span className="flex-1 truncate text-sm">
                              {file.name}
                            </span>
                            <Button
                              type="button"
                              variant="ghost-destructive"
                              size="xs"
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
                            >
                              {t(
                                'modals.uploadDoc.connectors.googleDrive.remove',
                              )}
                            </Button>
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
