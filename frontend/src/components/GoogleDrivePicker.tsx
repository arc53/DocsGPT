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
  initialSelectedFiles?: string[];
  initialSelectedFolders?: string[];
}

const GoogleDrivePicker: React.FC<GoogleDrivePickerProps> = ({
  token,
  onSelectionChange,
  initialSelectedFiles = [],
  initialSelectedFolders = [],
}) => {
  const [selectedFiles, setSelectedFiles] = useState<PickerFile[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<PickerFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [userEmail, setUserEmail] = useState<string>('');
  const [isConnected, setIsConnected] = useState(false);
  const [authError, setAuthError] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string | null>(null);
  
  const [openPicker] = useDrivePicker();
  
  useEffect(() => {
    const sessionToken = getSessionToken('google_drive');
    if (sessionToken) {
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
        return;
      }

      const validateData = await validateResponse.json();
      if (validateData.success) {
        setUserEmail(validateData.user_email || 'Connected User');
        setIsConnected(true);
        setAuthError('');
        setAccessToken(validateData.access_token || null);
      } else {
        setIsConnected(false);
        setAuthError(validateData.error || 'Session expired. Please reconnect your account.');
      }
    } catch (error) {
      console.error('Error validating session:', error);
      setAuthError('Failed to validate session. Please reconnect.');
      setIsConnected(false);
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
      openPicker({
        clientId: import.meta.env.VITE_GOOGLE_CLIENT_ID,
        developerKey: import.meta.env.VITE_GOOGLE_API_KEY,
        viewId: "DOCS_IMAGES_AND_VIDEOS",
        showUploadView: false,
        showUploadFolders: false,
        supportDrives: true,
        multiselect: true,
        token: accessToken,
        viewMimeTypes: 'application/vnd.google-apps.folder,application/vnd.google-apps.document,application/pdf',
        callbackFunction: (data:any) => {
          setIsLoading(false);
          if (data.action === 'picked') {
            const docs = data.docs;
          
            const files: PickerFile[] = [];
            const folders: PickerFile[] = [];
            
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
                folders.push(item);
              } else {
                files.push(item);
              }
            });
            
            setSelectedFiles(files);
            setSelectedFolders(folders);
            
            const fileIds = files.map(file => file.id);
            const folderIds = folders.map(folder => folder.id);
            
            console.log('Selected file IDs:', fileIds);
            console.log('Selected folder IDs:', folderIds);
            
            onSelectionChange(fileIds, folderIds);
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
    onSelectionChange([], []);
  };

  if (!isConnected) {
    return (
      <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A] p-6">
        {authError && (
          <div className="text-red-500 text-sm mb-4 text-center">{authError}</div>
        )}
        <ConnectorAuth
          provider="google_drive"
          onSuccess={(data) => {
            setUserEmail(data.user_email || 'Connected User');
            setIsConnected(true);
            setAuthError('');

            if (data.session_token) {
              setSessionToken('google_drive', data.session_token);
            }
          }}
          onError={(error) => {
            setAuthError(error);
            setIsConnected(false);
          }}
        />
      </div>
    );
  }

  return (
    <div className="border border-[#EEE6FF78] rounded-lg dark:border-[#6A6A6A]">
      <div className="p-3">
        <div className="w-full flex items-center justify-between rounded-[10px] bg-[#8FDD51] px-4 py-2 text-[#212121] font-medium text-sm">
          <div className="flex items-center gap-2">
            <svg className="h-4 w-4" viewBox="0 0 24 24">
              <path fill="currentColor" d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z" />
            </svg>
            <span>Connected as {userEmail}</span>
          </div>
          <button
            onClick={handleDisconnect}
            className="text-[#212121] hover:text-gray-700 font-medium text-xs underline"
          >
            Disconnect
          </button>
        </div>
      </div>

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
            {/* Display folders */}
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

            {/* Display files */}
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
  );
};

export default GoogleDrivePicker;
