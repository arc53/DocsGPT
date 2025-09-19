import React, { useState, useEffect } from 'react';
import useDrivePicker from 'react-google-drive-picker';

import ConnectorAuth from './ConnectorAuth';
import { getSessionToken, setSessionToken, removeSessionToken } from '../utils/providerUtils';


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
      const apiHost = import.meta.env.VITE_API_HOST;
      const validateResponse = await fetch(`${apiHost}/api/connectors/validate-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ provider: 'google_drive', session_token: sessionToken })
      });

      if (!validateResponse.ok) {
        setIsConnected(false);
        setAuthError('Session expired. Please reconnect to Google Drive.');
        setIsValidating(false);
        return false;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(validateData.user_email || 'Connected User');
        setIsConnected(true);
        setAuthError('');
        setAccessToken(validateData.access_token || null);
        setIsValidating(false);
        return true;
      } else {
        setIsConnected(false);
        setAuthError(validateData.error || 'Session expired. Please reconnect your account.');
        setIsValidating(false);
        return false;
      }
    } catch (error) {
      console.error('Error validating session:', error);
      setAuthError('Failed to validate session. Please reconnect.');
      setIsConnected(false);
      setIsValidating(false);
      return false;
    }
  };

  const handleOpenPicker = async () => {
    setIsLoading(true);
    
    const sessionToken = getSessionToken('google_drive');
    
    if (!sessionToken) {
      setAuthError('No valid session found. Please reconnect to Google Drive.');
      setIsLoading(false);
      return;
    }
    
    if (!accessToken) {
      setAuthError('No access token available. Please reconnect to Google Drive.');
      setIsLoading(false);
      return;
    }
    
    try {
      const clientId: string = import.meta.env.VITE_GOOGLE_CLIENT_ID;
      const developerKey : string = import.meta.env.VITE_GOOGLE_API_KEY;

      // Derive appId from clientId (extract numeric part before first dash)
      const appId = clientId ? clientId.split('-')[0] : null;

      if (!clientId || !developerKey || !appId) {
        console.error('Missing Google Drive configuration');

        setIsLoading(false);
        return;
      }

      openPicker({
        clientId: clientId,
        developerKey: developerKey,
        appId: appId,
        setSelectFolderEnabled: true,
        viewId: "DOCS",
        showUploadView: false,
        showUploadFolders: true,
        supportDrives: false,
        multiselect: true,
        token: accessToken,
        viewMimeTypes: 'application/vnd.google-apps.folder,application/vnd.google-apps.document,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/msword,application/vnd.ms-powerpoint,application/vnd.ms-excel,text/plain,text/csv,text/html,application/rtf,image/jpeg,image/jpg,image/png',
        callbackFunction: (data:any) => {
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
                sizeBytes: doc.sizeBytes
              };

              if (doc.mimeType === 'application/vnd.google-apps.folder') {
                newFolders.push(item);
              } else {
                newFiles.push(item);
              }
            });

            setSelectedFiles(prevFiles => {
              const existingFileIds = new Set(prevFiles.map(file => file.id));
              const uniqueNewFiles = newFiles.filter(file => !existingFileIds.has(file.id));
              return [...prevFiles, ...uniqueNewFiles];
            });

            setSelectedFolders(prevFolders => {
              const existingFolderIds = new Set(prevFolders.map(folder => folder.id));
              const uniqueNewFolders = newFolders.filter(folder => !existingFolderIds.has(folder.id));
              return [...prevFolders, ...uniqueNewFolders];
            });
            onSelectionChange(
              [...selectedFiles, ...newFiles].map(file => file.id),
              [...selectedFolders, ...newFolders].map(folder => folder.id)
            );
          }
        },
      });
    } catch (error) {
      console.error('Error opening picker:', error);
      setAuthError('Failed to open file picker. Please try again.');
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
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({ provider: 'google_drive', session_token: sessionToken })
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

  const ConnectedStateSkeleton = () => (
    <div className="mb-4">
      <div className="w-full flex items-center justify-between rounded-[10px] bg-gray-200 dark:bg-gray-700 px-4 py-2 animate-pulse">
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 bg-gray-300 dark:bg-gray-600 rounded"></div>
          <div className="h-4 w-32 bg-gray-300 dark:bg-gray-600 rounded"></div>
        </div>
        <div className="h-4 w-16 bg-gray-300 dark:bg-gray-600 rounded"></div>
      </div>
    </div>
  );

  const FilesSectionSkeleton = () => (
    <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A]">
      <div className="p-4">
        <div className="flex justify-between items-center mb-4">
          <div className="h-5 w-24 bg-gray-200 dark:bg-gray-700 rounded animate-pulse"></div>
          <div className="h-8 w-24 bg-gray-200 dark:bg-gray-700 rounded animate-pulse"></div>
        </div>
        <div className="h-4 w-40 bg-gray-200 dark:bg-gray-700 rounded animate-pulse"></div>
      </div>
    </div>
  );

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
            label="Connect to Google Drive"
            onSuccess={(data) => {
              setUserEmail(data.user_email || 'Connected User');
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
            <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A]">
              <div className="p-4">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-sm font-medium">Selected Files</h3>
                  <button
                    onClick={() => handleOpenPicker()}
                    className="bg-[#A076F6] hover:bg-[#8A5FD4] text-white text-sm py-1 px-3 rounded-md"
                    disabled={isLoading}
                  >
                    {isLoading ? 'Loading...' : 'Select Files'}
                  </button>
                </div>

                {selectedFiles.length === 0 && selectedFolders.length === 0 ? (
                  <p className="text-gray-600 dark:text-gray-400 text-sm">No files or folders selected</p>
                ) : (
                  <div className="max-h-60 overflow-y-auto">
                    {selectedFolders.length > 0 && (
                      <div className="mb-2">
                        <h4 className="text-xs font-medium text-gray-500 mb-1">Folders</h4>
                        {selectedFolders.map((folder) => (
                          <div key={folder.id} className="flex items-center p-2 border-b border-gray-200 dark:border-gray-700">
                            <img src={folder.iconUrl} alt="Folder" className="w-5 h-5 mr-2" />
                            <span className="text-sm truncate flex-1">{folder.name}</span>
                            <button
                              onClick={() => {
                                const newSelectedFolders = selectedFolders.filter(f => f.id !== folder.id);
                                setSelectedFolders(newSelectedFolders);
                                onSelectionChange(
                                  selectedFiles.map(f => f.id),
                                  newSelectedFolders.map(f => f.id)
                                );
                              }}
                              className="text-red-500 hover:text-red-700 text-sm ml-2"
                            >
                              Remove
                            </button>
                          </div>
                        ))}
                      </div>
                    )}

                    {selectedFiles.length > 0 && (
                      <div>
                        <h4 className="text-xs font-medium text-gray-500 mb-1">Files</h4>
                        {selectedFiles.map((file) => (
                          <div key={file.id} className="flex items-center p-2 border-b border-gray-200 dark:border-gray-700">
                            <img src={file.iconUrl} alt="File" className="w-5 h-5 mr-2" />
                            <span className="text-sm truncate flex-1">{file.name}</span>
                            <button
                              onClick={() => {
                                const newSelectedFiles = selectedFiles.filter(f => f.id !== file.id);
                                setSelectedFiles(newSelectedFiles);
                                onSelectionChange(
                                  newSelectedFiles.map(f => f.id),
                                  selectedFolders.map(f => f.id)
                                );
                              }}
                              className="text-red-500 hover:text-red-700 text-sm ml-2"
                            >
                              Remove
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
