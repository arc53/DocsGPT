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
  const [popupPosition, setPopupPosition] = useState({ top: 0, left: 0, maxHeight: 0, showAbove: false });

  useLayoutEffect(() => {
    if (!isOpen || !anchorRef.current) return;
    
    const updatePosition = () => {
      if (!anchorRef.current) return;
      
      const rect = anchorRef.current.getBoundingClientRect();
      const viewportHeight = window.innerHeight;
      const viewportWidth = window.innerWidth;
      
      const spaceAbove = rect.top;
      const spaceBelow = viewportHeight - rect.bottom;
      const showAbove = spaceAbove > spaceBelow && spaceAbove >= 300;
      const maxHeight = showAbove ? spaceAbove - 16 : spaceBelow - 16;

      const left = Math.min(
        rect.left,
        viewportWidth - Math.min(462, viewportWidth * 0.95) - 10
      );
      
      setPopupPosition({
        top: showAbove ? rect.top - 8 : rect.bottom + 8,
        left,
        maxHeight: Math.min(600, maxHeight),
        showAbove
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

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose, anchorRef, isOpen]);

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

  const filteredTools = userTools.filter((tool) =>
    tool.displayName.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div
      ref={popupRef}
      className="fixed z-[9999] rounded-lg border border-light-silver dark:border-dim-gray bg-lotion dark:bg-charleston-green-2 shadow-[0px_9px_46px_8px_#0000001F,0px_24px_38px_3px_#00000024,0px_11px_15px_-7px_#00000033]"
      style={{
        top: popupPosition.showAbove ? popupPosition.top : undefined,
        bottom: popupPosition.showAbove ? undefined : window.innerHeight - popupPosition.top,
        left: popupPosition.left,
        maxWidth: Math.min(462, window.innerWidth * 0.95),
        width: '100%',
        height: popupPosition.maxHeight,
        transform: popupPosition.showAbove ? 'translateY(-100%)' : 'none',
      }}
    >
      <div className="flex flex-col h-full">
        <div className="p-4 flex-shrink-0">
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
        </div>

        {loading ? (
          <div className="flex justify-center py-4 flex-grow">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-gray-900 dark:border-white"></div>
          </div>
        ) : (
          <div className="mx-4 border border-[#D9D9D9] dark:border-dim-gray rounded-md overflow-hidden flex-grow">
            <div className="h-full overflow-y-auto [&::-webkit-scrollbar-thumb]:bg-[#888] [&::-webkit-scrollbar-thumb]:hover:bg-[#555] [&::-webkit-scrollbar-track]:bg-[#E2E8F0] dark:[&::-webkit-scrollbar-track]:bg-[#2C2E3C]">
              {filteredTools.length === 0 ? (
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
                filteredTools.map((tool) => (
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

        <div className="p-4 flex-shrink-0 opacity-75 hover:opacity-100 transition-opacity duration-200">
          <a
            href="/settings/tools"
            className="text-base text-purple-30 font-medium inline-flex items-center"
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
