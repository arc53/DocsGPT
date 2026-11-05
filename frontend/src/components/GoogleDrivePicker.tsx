import { envVar } from '@/env';
import { File, Folder, X } from 'lucide-react';
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
import { formatCount } from '../utils/dateTimeUtils';
import { formatBytes } from '../utils/stringUtils';
import ConnectorAuth from './ConnectorAuth';
import { Alert, AlertDescription } from './ui/alert';
import { Avatar } from './ui/avatar';
import { Button } from './ui/button';
import { Card } from './ui/card';
import { IconButton } from './ui/icon-button';
import { ListRow, ListRows } from './ui/list-row';
import { SectionHeader } from './ui/section-header';

interface PickerFile {
  id: string;
  name: string;
  mimeType: string;
  sizeBytes?: string;
}

// The file types the worker can ingest; folders are shown on top of these.
const VIEW_MIME_TYPES = [
  'application/vnd.google-apps.document',
  'application/vnd.google-apps.presentation',
  'application/vnd.google-apps.spreadsheet',
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'application/msword',
  'application/vnd.ms-powerpoint',
  'application/vnd.ms-excel',
  'text/plain',
  'text/csv',
  'text/html',
  'text/markdown',
  'text/x-rst',
  'application/json',
  'application/epub+zip',
  'application/rtf',
  'image/jpeg',
  'image/jpg',
  'image/png',
].join(',');

const FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder';

/**
 * The type filter a view gets. With any filter set, Google's Select ignores a
 * highlighted folder, even when the folder type is listed, so a view where
 * folders can be picked is left unfiltered; the worker skips types it cannot
 * read. Files-only views keep the filter.
 */
const viewMimeTypes = (foldersSelectable: boolean): string | undefined =>
  foldersSelectable ? undefined : VIEW_MIME_TYPES;

/** The part of Google's Picker API the shared-drives tab is built with. */
interface PickerDocsView {
  setEnableDrives(enabled: boolean): PickerDocsView;
  setIncludeFolders(included: boolean): PickerDocsView;
  setSelectFolderEnabled(enabled: boolean): PickerDocsView;
  setMimeTypes(mimeTypes: string): PickerDocsView;
}
interface PickerApi {
  DocsView: new (viewId: unknown) => PickerDocsView;
  ViewId: Record<string, unknown>;
}

/**
 * A "Shared drives" tab for the picker. Built from the Picker API the
 * picker hook loads, so it is left out until that script is there.
 */
const sharedDrivesView = (
  foldersSelectable: boolean,
): PickerDocsView[] | undefined => {
  const pickerApi = (window as { google?: { picker?: PickerApi } }).google
    ?.picker;
  if (!pickerApi) return undefined;
  const view = new pickerApi.DocsView(pickerApi.ViewId.DOCS)
    .setEnableDrives(true)
    .setIncludeFolders(true)
    .setSelectFolderEnabled(foldersSelectable);
  const mimeTypes = viewMimeTypes(foldersSelectable);
  return [mimeTypes ? view.setMimeTypes(mimeTypes) : view];
};

/** Why the last attempt to open the picker failed. */
type PickerError = 'expired' | 'validateFailed' | 'pickerFailed' | null;

/**
 * How the server reads a picked folder, sent with the picker token: with
 * the account's own sign-in, through a service account the folder must be
 * shared with (`share_with`), or not at all (files only).
 */
interface FolderAccess {
  folders?: 'account' | 'service_account' | 'off';
  share_with?: string;
}

interface GoogleDrivePickerProps {
  token: string | null;
  /**
   * The OAuth client the server signs in with. Google grants what is
   * picked to this client's project only, so it wins over
   * VITE_GOOGLE_CLIENT_ID.
   */
  clientId?: string | null;
  /**
   * The Drive connection to pick from, chosen by the caller (the connect
   * wizard). Left out, the first connected one, with the picker's own
   * sign-in.
   */
  connectionId?: string | null;
  /** Reports the account the picker uses, so the upload can name it. */
  onConnectionChange?: (connectionId: string | null) => void;
  onSelectionChange: (fileIds: string[], folderIds?: string[]) => void;
  /** Called with the first item's name when the selection goes from empty to one. */
  onFirstPickName?: (name: string) => void;
  /** Signs the connection in again when its sign-in expired. */
  onReconnect?: () => void;
}

/**
 * Pick Drive files with Google's own picker; what was picked is listed
 * under the Select files button as rows that can be removed again.
 */
const GoogleDrivePicker: React.FC<GoogleDrivePickerProps> = ({
  token,
  clientId: serverClientId,
  connectionId: suppliedConnectionId,
  onConnectionChange,
  onSelectionChange,
  onFirstPickName,
  onReconnect,
}) => {
  const { t } = useTranslation();
  const dispatch = useDispatch<AppDispatch>();
  const connections = useSelector(selectConnections);
  const supplied = suppliedConnectionId !== undefined;
  const [signedInId, setSignedInId] = useState<string | null>(null);
  const accounts = connections.filter(
    (c) => c.connector_key === 'google_drive' && c.status === 'connected',
  );
  const activeConnectionId = supplied
    ? suppliedConnectionId
    : (signedInId ?? accounts[0]?.id ?? null);
  const activeAccount = accounts.find((a) => a.id === activeConnectionId);
  const isConnected = !!activeConnectionId;
  const [selectedFiles, setSelectedFiles] = useState<PickerFile[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<PickerFile[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<PickerError>(null);
  const [authError, setAuthError] = useState('');
  const [folderAccess, setFolderAccess] = useState<FolderAccess>({});

  const [openPicker] = useDrivePicker();

  useEffect(() => {
    onConnectionChange?.(activeConnectionId);
  }, [activeConnectionId]);

  // The Picker runs in the browser and needs an access token. It is fetched
  // per use and kept in memory only; the refresh token never leaves the server.
  const fetchAccessToken = async (): Promise<
    (FolderAccess & { access_token: string }) | null
  > => {
    if (!activeConnectionId) return null;
    try {
      const data = await connectorsService.pickerToken(
        activeConnectionId,
        token,
      );
      if (!data?.success || !data.access_token) {
        setError('expired');
        dispatch(loadConnectors({ token }));
        return null;
      }
      setError(null);
      setFolderAccess({ folders: data.folders, share_with: data.share_with });
      return data;
    } catch (err) {
      console.error('Error fetching the picker token:', err);
      setError('validateFailed');
      return null;
    }
  };

  const handleOpenPicker = async () => {
    setIsLoading(true);
    const picker = await fetchAccessToken();
    if (!picker) {
      setIsLoading(false);
      return;
    }
    const foldersSelectable = picker.folders !== 'off';
    try {
      const clientId: string =
        serverClientId || envVar('VITE_GOOGLE_CLIENT_ID');
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
        // Folders are picked like files; the worker downloads their contents.
        // Shown either way, so a user can open them to pick files inside.
        setIncludeFolders: true,
        setSelectFolderEnabled: foldersSelectable,
        viewId: 'DOCS',
        showUploadView: false,
        showUploadFolders: false,
        supportDrives: true,
        customViews: sharedDrivesView(foldersSelectable),
        multiselect: true,
        token: picker.access_token,
        viewMimeTypes: viewMimeTypes(foldersSelectable),
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
                sizeBytes: doc.sizeBytes,
              };

              if (doc.mimeType === FOLDER_MIME_TYPE) {
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
      setError('pickerFailed');
      setIsLoading(false);
    }
  };

  const remove = (item: PickerFile, folder: boolean) => {
    const files = folder
      ? selectedFiles
      : selectedFiles.filter((f) => f.id !== item.id);
    const folders = folder
      ? selectedFolders.filter((f) => f.id !== item.id)
      : selectedFolders;
    setSelectedFiles(files);
    setSelectedFolders(folders);
    onSelectionChange(
      files.map((f) => f.id),
      folders.map((f) => f.id),
    );
  };

  const row = (item: PickerFile, folder: boolean) => (
    <ListRow
      key={item.id}
      leading={
        <Avatar size="sm" shape="square" variant="icon">
          {folder ? (
            <Folder className="size-4" aria-hidden />
          ) : (
            <File className="size-4" aria-hidden />
          )}
        </Avatar>
      }
      title={item.name}
      description={
        folder
          ? t('filePicker.folder')
          : item.sizeBytes
            ? formatBytes(Number(item.sizeBytes))
            : undefined
      }
      trailing={
        <IconButton
          variant="ghost-muted"
          size="icon-sm"
          icon={X}
          label={t('modals.uploadDoc.connectors.googleDrive.removeItem', {
            name: item.name,
            interpolation: { escapeValue: false },
          })}
          onClick={() => remove(item, folder)}
        />
      }
    />
  );

  const pickedCount = selectedFiles.length + selectedFolders.length;

  return (
    <div className="flex flex-col gap-3">
      {!supplied && (
        <ConnectorAuth
          provider="google_drive"
          label={t('modals.uploadDoc.connectors.googleDrive.connect')}
          icon={<ConnectorIcon icon="drive" className="size-5" />}
          onSuccess={(data) => {
            setAuthError('');
            dispatch(loadConnectors({ token }));
            if (data.connection_id) setSignedInId(data.connection_id);
          }}
          onError={setAuthError}
          isConnected={isConnected}
          userEmail={
            activeAccount?.account_label ||
            t('modals.uploadDoc.connectors.auth.connectedUser')
          }
          errorMessage={authError}
        />
      )}

      {error && (
        <Alert variant="destructive">
          <AlertDescription>
            {error === 'expired'
              ? t('settings.connectors.detail.expired')
              : t(`modals.uploadDoc.connectors.googleDrive.${error}`)}
            {error === 'expired' && onReconnect ? (
              <>
                {' '}
                <Button
                  type="button"
                  variant="link"
                  size="text"
                  tone="current"
                  onClick={onReconnect}
                >
                  {t('settings.connectors.status.reconnect')}
                </Button>
              </>
            ) : null}
          </AlertDescription>
        </Alert>
      )}

      {isConnected && (
        <>
          <div className="flex items-center justify-between gap-3">
            <SectionHeader
              as="h3"
              size="xs"
              title={t('modals.uploadDoc.connectors.googleDrive.selectedFiles')}
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
          {folderAccess.folders === 'off' && (
            <p className="text-muted-foreground text-xs">
              {t('modals.uploadDoc.connectors.googleDrive.filesOnly')}
            </p>
          )}
          {pickedCount === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t('modals.uploadDoc.connectors.googleDrive.noFilesSelected')}
            </p>
          ) : (
            <>
              <Card
                variant="outline"
                padding="none"
                className="overflow-hidden"
              >
                <ListRows>
                  {selectedFolders.map((folder) => row(folder, true))}
                  {selectedFiles.map((file) => row(file, false))}
                </ListRows>
              </Card>
              <p className="text-muted-foreground text-xs">
                {t('filePicker.itemsSelected', {
                  count: pickedCount,
                  formatted: formatCount(pickedCount),
                })}
              </p>
            </>
          )}
          {folderAccess.folders === 'service_account' &&
            folderAccess.share_with &&
            selectedFolders.length > 0 && (
              <Alert variant="info">
                <AlertDescription>
                  {t('modals.uploadDoc.connectors.googleDrive.shareFolders')}{' '}
                  <span className="font-mono wrap-anywhere select-all">
                    {folderAccess.share_with}
                  </span>
                </AlertDescription>
              </Alert>
            )}
        </>
      )}
    </div>
  );
};

export default GoogleDrivePicker;
