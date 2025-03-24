import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { selectToken } from '../preferences/preferenceSlice';
import userService from '../api/services/userService';
import { UserToolType } from '../settings/types';
import Input from './Input';
import RedirectIcon from '../assets/redirect.svg';
import NoFilesIcon from '../assets/no-files.svg';
import NoFilesDarkIcon from '../assets/no-files-dark.svg';
import CheckmarkIcon from '../assets/checkmark.svg';
import { useDarkTheme } from '../hooks';

interface ToolsPopupProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement>;
}

export default function ToolsPopup({
  isOpen,
  onClose,
  anchorRef,
}: ToolsPopupProps) {
  const { t } = useTranslation();
  const token = useSelector(selectToken);
  const [userTools, setUserTools] = React.useState<UserToolType[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [isDarkTheme] = useDarkTheme();
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        popupRef.current &&
        !popupRef.current.contains(event.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(event.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose, anchorRef]);

  useEffect(() => {
    if (isOpen) {
      getUserTools();
    }
  }, [isOpen, token]);

  const getUserTools = () => {
    setLoading(true);
    userService
      .getUserTools(token)
      .then((res) => {
        return res.json();
      })
      .then((data) => {
        setUserTools(data.tools);
        setLoading(false);
      })
      .catch((error) => {
        console.error('Error fetching tools:', error);
        setLoading(false);
      });
  };

  const updateToolStatus = (toolId: string, newStatus: boolean) => {
    userService
      .updateToolStatus({ id: toolId, status: newStatus }, token)
      .then(() => {
        setUserTools((prevTools) =>
          prevTools.map((tool) =>
            tool.id === toolId ? { ...tool, status: newStatus } : tool,
          ),
        );
      })
      .catch((error) => {
        console.error('Failed to update tool status:', error);
      });
  };

  if (!isOpen) return null;

  return (
    <div
      ref={popupRef}
      className="absolute z-10 w-[462px] rounded-lg border border-light-silver dark:border-dim-gray bg-lotion dark:bg-charleston-green-2 shadow-lg"
      style={{
        bottom: anchorRef.current
          ? window.innerHeight -
            anchorRef.current.getBoundingClientRect().top +
            10
          : 0,
        left: anchorRef.current
          ? anchorRef.current.getBoundingClientRect().left
          : 0,
        position: 'fixed',
        zIndex: 9999,
      }}
    >
      <div className="p-4">
        <h3 className="text-lg font-medium text-gray-900 dark:text-white mb-4">
          {t('settings.tools.label')}
        </h3>

        <Input
          id="tool-search"
          name="tool-search"
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder={t('settings.tools.searchPlaceholder')}
          labelBgClassName="bg-lotion dark:bg-charleston-green-2"
          borderVariant="thin"
          className="mb-4"
        />

        {loading ? (
          <div className="flex justify-center py-4">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900 dark:border-white"></div>
          </div>
        ) : (
          <div className="border border-[#D9D9D9] dark:border-dim-gray rounded-md overflow-hidden">
            <div className="h-[440px] overflow-y-auto">
              {userTools.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-8">
                  <img
                    src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                    alt="No tools found"
                    className="h-24 w-24 mx-auto mb-4"
                  />
                  <p className="text-gray-500 dark:text-gray-400 text-center">
                    {t('settings.tools.noToolsFound')}
                  </p>
                </div>
              ) : (
                userTools
                  .filter((tool) =>
                    tool.displayName
                      .toLowerCase()
                      .includes(searchTerm.toLowerCase()),
                  )
                  .map((tool) => (
                    <div
                      key={tool.id}
                      onClick={() => updateToolStatus(tool.id, !tool.status)}
                      className="flex items-center justify-between p-3 border-b border-[#D9D9D9] dark:border-dim-gray hover:bg-gray-100 dark:hover:bg-charleston-green-3"
                    >
                      <div className="flex items-center">
                        <img
                          src={`/toolIcons/tool_${tool.name}.svg`}
                          alt={`${tool.displayName} icon`}
                          className="h-6 w-6 mr-4"
                        />
                        <div>
                          <p className="text-sm font-medium text-gray-900 dark:text-white">
                            {tool.displayName}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center">
                        <img
                          src={tool.status ? CheckmarkIcon : ''}
                          alt="Tool enabled"
                          width={14}
                          height={14}
                          className={`${!tool.status && 'hidden'}`}
                        />
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>
        )}

        <div className="mt-4 flex justify-start">
          <a
            href="/settings/tools"
            className="text-base text-purple-30 font-medium hover:text-violets-are-blue flex items-center"
          >
            {t('settings.tools.manageTools')}
            <img
              src={RedirectIcon}
              alt="Go to tools"
              className="ml-2 h-[11px] w-[11px]"
            />
          </a>
        </div>
      </div>
    </div>
  );
}
