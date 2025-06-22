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
  anchorRef: React.RefObject<HTMLButtonElement | null>;
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
  const [popupPosition, setPopupPosition] = useState({
    top: 0,
    left: 0,
    maxHeight: 0,
    showAbove: false,
  });

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
        viewportWidth - Math.min(462, viewportWidth * 0.95) - 10,
      );

      setPopupPosition({
        top: showAbove ? rect.top - 8 : rect.bottom + 8,
        left,
        maxHeight: Math.min(600, maxHeight),
        showAbove,
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
    tool.displayName.toLowerCase().includes(searchTerm.toLowerCase()),
  );

  return (
    <div
      ref={popupRef}
      className="border-light-silver bg-lotion dark:border-dim-gray dark:bg-charleston-green-2 fixed z-9999 rounded-lg border shadow-[0px_9px_46px_8px_#0000001F,0px_24px_38px_3px_#00000024,0px_11px_15px_-7px_#00000033]"
      style={{
        top: popupPosition.showAbove ? popupPosition.top : undefined,
        bottom: popupPosition.showAbove
          ? undefined
          : window.innerHeight - popupPosition.top,
        left: popupPosition.left,
        maxWidth: Math.min(462, window.innerWidth * 0.95),
        width: '100%',
        height: popupPosition.maxHeight,
        transform: popupPosition.showAbove ? 'translateY(-100%)' : 'none',
      }}
    >
      <div className="flex h-full flex-col">
        <div className="shrink-0 p-4">
          <h3 className="mb-4 text-lg font-medium text-gray-900 dark:text-white">
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
          <div className="flex grow justify-center py-4">
            <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-gray-900 dark:border-white"></div>
          </div>
        ) : (
          <div className="dark:border-dim-gray mx-4 grow overflow-hidden rounded-md border border-[#D9D9D9]">
            <div className="h-full overflow-y-auto [&::-webkit-scrollbar-thumb]:bg-[#888] [&::-webkit-scrollbar-thumb]:hover:bg-[#555] [&::-webkit-scrollbar-track]:bg-[#E2E8F0] dark:[&::-webkit-scrollbar-track]:bg-[#2C2E3C]">
              {filteredTools.length === 0 ? (
                <div className="flex h-full flex-col items-center justify-center py-8">
                  <img
                    src={isDarkTheme ? NoFilesDarkIcon : NoFilesIcon}
                    alt="No tools found"
                    className="mx-auto mb-4 h-24 w-24"
                  />
                  <p className="text-center text-gray-500 dark:text-gray-400">
                    {t('settings.tools.noToolsFound')}
                  </p>
                </div>
              ) : (
                filteredTools.map((tool) => (
                  <div
                    key={tool.id}
                    onClick={() => updateToolStatus(tool.id, !tool.status)}
                    className="dark:border-dim-gray dark:hover:bg-charleston-green-3 flex items-center justify-between border-b border-[#D9D9D9] p-3 hover:bg-gray-100"
                  >
                    <div className="mr-3 flex grow items-center">
                      <img
                        src={`/toolIcons/tool_${tool.name}.svg`}
                        alt={`${tool.displayName} icon`}
                        className="mr-4 h-5 w-5 shrink-0"
                      />
                      <div className="overflow-hidden">
                        <p className="overflow-hidden text-xs font-medium text-ellipsis whitespace-nowrap text-gray-900 dark:text-white">
                          {tool.customName || tool.displayName}
                        </p>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center">
                      <div
                        className={`flex h-4 w-4 items-center justify-center border border-[#C6C6C6] p-[0.5px] dark:border-[#757783]`}
                      >
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

        <div className="shrink-0 p-4 opacity-75 transition-opacity duration-200 hover:opacity-100">
          <a
            href="/settings/tools"
            className="text-purple-30 inline-flex items-center text-base font-medium"
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
