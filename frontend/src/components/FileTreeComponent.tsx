import React, { useEffect, useState, useRef } from 'react';
import { useSelector } from 'react-redux';
import userService from '../api/services/userService';
import FileIcon from '../assets/file.svg';
import FolderIcon from '../assets/folder.svg';
import ArrowLeft from '../assets/arrow-left.svg';
import ThreeDots from '../assets/three-dots.svg';
import EyeView from '../assets/eye-view.svg';
import OutlineSource from '../assets/outline-source.svg';
import Trash from '../assets/red-trash.svg';
import Spinner from './Spinner';
import { useTranslation } from 'react-i18next';
import ContextMenu, { MenuOption } from './ContextMenu';

interface FileNode {
  type?: string;
  token_count?: number;
  size_bytes?: number;
  [key: string]: any;
}

interface DirectoryStructure {
  [key: string]: FileNode;
}

interface FileTreeComponentProps {
  docId: string;
  sourceName: string;
  onBackToDocuments?: () => void;
}

const FileTreeComponent: React.FC<FileTreeComponentProps> = ({
  docId,
  sourceName,
  onBackToDocuments,
}) => {
  const { t } = useTranslation();
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [directoryStructure, setDirectoryStructure] =
    useState<DirectoryStructure | null>(null);
  const [currentPath, setCurrentPath] = useState<string[]>([]);
  const token = useSelector((state: any) => state.auth?.token);
  const [activeMenuId, setActiveMenuId] = useState<string | null>(null);
  const menuRefs = useRef<{
    [key: string]: React.RefObject<HTMLDivElement | null>;
  }>({});

  useEffect(() => {
    const fetchDirectoryStructure = async () => {
      try {
        setLoading(true);
        const response = await userService.getDirectoryStructure(docId, token);
        const data = await response.json();

        if (data && data.directory_structure) {
          setDirectoryStructure(data.directory_structure);
        } else {
          setError('Invalid response format');
        }
      } catch (err) {
        setError('Failed to load directory structure');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    if (docId) {
      fetchDirectoryStructure();
    }
  }, [docId, token]);

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  const navigateToDirectory = (dirName: string) => {
    setCurrentPath((prev) => [...prev, dirName]);
  };

  const navigateUp = () => {
    setCurrentPath((prev) => prev.slice(0, -1));
  };

  const getCurrentDirectory = (): DirectoryStructure => {
    if (!directoryStructure) return {};

    let current: any = directoryStructure;
    for (const dir of currentPath) {
      if (current[dir] && !current[dir].type) {
        current = current[dir];
      } else {
        return {};
      }
    }
    return current;
  };

  const handleBackNavigation = () => {
    if (currentPath.length === 0) {
      if (onBackToDocuments) {
        onBackToDocuments();
      }
    } else {
      navigateUp();
    }
  };

  const getMenuRef = (itemId: string) => {
    if (!menuRefs.current[itemId]) {
      menuRefs.current[itemId] = React.createRef<HTMLDivElement>();
    }
    return menuRefs.current[itemId];
  };

  const handleMenuClick = (e: React.MouseEvent, itemId: string) => {
    e.preventDefault();
    e.stopPropagation();

    if (activeMenuId === itemId) {
      setActiveMenuId(null);
      return;
    }
    setActiveMenuId(itemId);
  };

  const getActionOptions = (name: string, isFile: boolean): MenuOption[] => {
    const options: MenuOption[] = [];

    if (isFile) {
      options.push({
        icon: EyeView,
        label: t('settings.documents.view'),
        onClick: (event: React.SyntheticEvent) => {
          event.stopPropagation();
          console.log('View file:', name);
          // View file action will be implemented later
        },
        iconWidth: 18,
        iconHeight: 18,
        variant: 'primary',
      });
    }

    options.push({
      icon: Trash,
      label: t('convTile.delete'),
      onClick: (event: React.SyntheticEvent) => {
        event.stopPropagation();
        console.log('Delete item:', name);
        // Delete action will be implemented later
      },
      iconWidth: 18,
      iconHeight: 18,
      variant: 'danger',
    });

    return options;
  };

  const renderPathNavigation = () => {
    return (
      <div className="mb-4 flex items-center text-sm">
        <button
          className="mr-3 flex h-[29px] w-[29px] items-center justify-center rounded-full border p-2 text-sm text-gray-400 dark:border-0 dark:bg-[#28292D] dark:text-gray-500 dark:hover:bg-[#2E2F34]"
          onClick={handleBackNavigation}
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3 w-3" />
        </button>

        <div className="flex items-center">
          <img src={OutlineSource} alt="source" className="mr-2 h-5 w-5" />
          <span className="text-purple-30 font-medium">{sourceName}</span>
          {currentPath.length > 0 && (
            <>
              <span className="mx-1 text-gray-500">/</span>
              {currentPath.map((dir, index) => (
                <React.Fragment key={index}>
                  <span className="text-gray-700 dark:text-gray-300">
                    {dir}
                  </span>
                  {index < currentPath.length - 1 && (
                    <span className="mx-1 text-gray-500">/</span>
                  )}
                </React.Fragment>
              ))}
            </>
          )}
        </div>
      </div>
    );
  };
  const renderFileTree = (structure: DirectoryStructure): React.ReactNode[] => {
    const entries = Object.entries(structure);
    const directories = entries.filter(([_, node]) => !node.type);
    const files = entries.filter(([_, node]) => node.type);

    return [
      ...directories.map(([name, node]) => {
        const itemId = `dir-${name}`;
        const menuRef = getMenuRef(itemId);

        return (
          <tr
            key={itemId}
            className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]"
          >
            <td className="px-4 py-2">
              <div
                className="flex cursor-pointer items-center"
                onClick={() => navigateToDirectory(name)}
              >
                <img src={FolderIcon} alt="Folder" className="mr-2 h-4 w-4" />
                <span className="text-sm">{name}</span>
              </div>
            </td>
            <td className="px-4 py-2 text-sm">-</td>
            <td className="px-4 py-2 text-sm">-</td>
            <td className="w-10 px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt="Menu"
                    className="opacity-60 hover:opacity-100"
                  />
                </button>
                <ContextMenu
                  isOpen={activeMenuId === itemId}
                  setIsOpen={(isOpen) =>
                    setActiveMenuId(isOpen ? itemId : null)
                  }
                  options={getActionOptions(name, false)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: 0, y: 8 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
      ...files.map(([name, node]) => {
        const itemId = `file-${name}`;
        const menuRef = getMenuRef(itemId);

        return (
          <tr
            key={itemId}
            className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]"
          >
            <td className="px-4 py-2">
              <div className="flex items-center">
                <img src={FileIcon} alt="File" className="mr-2 h-4 w-4" />
                <span className="text-sm">{name}</span>
              </div>
            </td>
            <td className="px-4 py-2 text-sm">
              {node.token_count?.toLocaleString() || '-'}
            </td>
            <td className="px-4 py-2 text-sm">
              {node.size_bytes ? formatBytes(node.size_bytes) : '-'}
            </td>
            <td className="w-10 px-4 py-2 text-sm">
              <div ref={menuRef} className="relative">
                <button
                  onClick={(e) => handleMenuClick(e, itemId)}
                  className="inline-flex h-[35px] w-[24px] shrink-0 items-center justify-center rounded-md transition-colors hover:bg-[#EBEBEB] dark:hover:bg-[#26272E]"
                  aria-label="Open menu"
                >
                  <img
                    src={ThreeDots}
                    alt="Menu"
                    className="opacity-60 hover:opacity-100"
                  />
                </button>
                <ContextMenu
                  isOpen={activeMenuId === itemId}
                  setIsOpen={(isOpen) =>
                    setActiveMenuId(isOpen ? itemId : null)
                  }
                  options={getActionOptions(name, true)}
                  anchorRef={menuRef}
                  position="bottom-left"
                  offset={{ x: 0, y: 8 }}
                />
              </div>
            </td>
          </tr>
        );
      }),
    ];
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  if (error) {
    return <div className="p-4 text-center text-red-500">{error}</div>;
  }

  if (!directoryStructure) {
    return (
      <div className="p-4 text-center text-gray-500">
        No directory structure available
      </div>
    );
  }

  const currentDirectory = getCurrentDirectory();

  return (
    <div className="w-full">
      <div className="mb-4">{renderPathNavigation()}</div>

      <div className="overflow-x-auto rounded-[6px] border border-[#D1D9E0] dark:border-[#6A6A6A]">
        <table className="min-w-full table-fixed bg-white dark:bg-gray-900">
          <thead className="bg-gray-100 dark:bg-gray-800">
            <tr className="border-b border-[#D1D9E0] dark:border-[#6A6A6A]">
              <th className="w-3/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
                Name
              </th>
              <th className="w-1/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
                Tokens
              </th>
              <th className="w-1/5 px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
                Size
              </th>
              <th className="w-[60px] px-4 py-3 text-left text-sm font-medium text-gray-700 dark:text-gray-300">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="[&>tr:last-child]:border-b-0">
            {renderFileTree(currentDirectory)}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default FileTreeComponent;
