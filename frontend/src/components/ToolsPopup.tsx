import React, { useEffect, useRef, useState, useLayoutEffect } from 'react';
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
  const [popupPosition, setPopupPosition] = useState({ bottom: 0, left: 0 });

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;
    
    const updatePosition = () => {
      if (!anchorRef.current) return;
      
      const rect = anchorRef.current.getBoundingClientRect();
      setPopupPosition({
        bottom: Math.min(
          window.innerHeight - rect.top + 10,
          window.innerHeight - 20
        ),
        left: Math.min(
          rect.left,
          window.innerWidth - Math.min(462, window.innerWidth * 0.95) - 10
        )
      });
    };
    
    updatePosition();
    window.addEventListener('resize', updatePosition);
    return () => window.removeEventListener('resize', updatePosition);
  }, [isOpen, anchorRef]);

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
      className="absolute z-10 w-[462px] max-w-[95vw] rounded-lg border border-light-silver dark:border-dim-gray bg-lotion dark:bg-charleston-green-2 shadow-[0px_9px_46px_8px_#0000001F,0px_24px_38px_3px_#00000024,0px_11px_15px_-7px_#00000033]"
      style={{
        bottom: popupPosition.bottom,
        left: popupPosition.left,
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
            <div 
              className="h-[calc(min(480px,100vh-220px))] overflow-y-auto [&::-webkit-scrollbar-thumb]:bg-[#888] [&::-webkit-scrollbar-thumb]:hover:bg-[#555] [&::-webkit-scrollbar-track]:bg-[#E2E8F0] dark:[&::-webkit-scrollbar-track]:bg-[#2C2E3C]"
             
            >
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
                      <div className="flex items-center flex-grow mr-3">
                        <img
                          src={`/toolIcons/tool_${tool.name}.svg`}
                          alt={`${tool.displayName} icon`}
                          className="h-5 w-5 mr-4 flex-shrink-0"
                        />
                        <div className="overflow-hidden">
                          <p className="text-xs font-medium text-gray-900 dark:text-white overflow-hidden overflow-ellipsis whitespace-nowrap">
                            {tool.displayName}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center flex-shrink-0">
                        <div className={`w-4 h-4 border flex items-center justify-center p-[0.5px] dark:border-[#757783] border-[#C6C6C6]`}>
                          {tool.status && (
                            <img
                              src={CheckmarkIcon}
                              alt="Tool enabled"
                              width={12}
                              height={12}
                            />
                          )}
                        </div>
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
