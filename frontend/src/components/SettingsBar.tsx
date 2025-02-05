import React, { useCallback, useRef, useState } from 'react';
import ArrowLeft from '../assets/arrow-left.svg';
import ArrowRight from '../assets/arrow-right.svg';
import { useTranslation } from 'react-i18next';

type HiddenGradientType = 'left' | 'right' | undefined;

const useTabs = () => {
  const { t } = useTranslation();
  const tabs = [
    t('settings.general.label'),
    t('settings.documents.label'),
    t('settings.apiKeys.label'),
    t('settings.analytics.label'),
    t('settings.logs.label'),
    t('settings.tools.label'),
  ];
  return tabs;
};

interface SettingsBarProps {
  setActiveTab: React.Dispatch<React.SetStateAction<string>>;
  activeTab: string;
}

const SettingsBar = ({ setActiveTab, activeTab }: SettingsBarProps) => {
  const [hiddenGradient, setHiddenGradient] =
    useState<HiddenGradientType>('left');
  const containerRef = useRef<null | HTMLDivElement>(null);
  const tabs = useTabs();
  const scrollTabs = useCallback(
    (direction: number) => {
      if (containerRef.current) {
        const container = containerRef.current;
        container.scrollLeft += direction * 100; // Adjust the scroll amount as needed
        if (container.scrollLeft === 0) {
          setHiddenGradient('left');
        } else if (
          container.scrollLeft + container.offsetWidth ===
          container.scrollWidth
        ) {
          setHiddenGradient('right');
        } else {
          setHiddenGradient(undefined);
        }
      }
    },
    [containerRef.current],
  );
  return (
    <div className="relative mt-6 flex flex-row items-center space-x-1 md:space-x-0 overflow-auto">
      <div
        className={`${hiddenGradient === 'left' ? 'hidden' : ''} md:hidden absolute inset-y-0 left-6 w-14 bg-gradient-to-r from-white dark:from-raisin-black pointer-events-none`}
      ></div>
      <div
        className={`${hiddenGradient === 'right' ? 'hidden' : ''} md:hidden absolute inset-y-0 right-6 w-14 bg-gradient-to-l from-white dark:from-raisin-black pointer-events-none`}
      ></div>

      <div className="md:hidden z-10">
        <button
          onClick={() => scrollTabs(-1)}
          className="flex h-6 w-6 items-center rounded-full justify-center transition-all hover:bg-gray-200 dark:hover:bg-gray-700"
          aria-label="Scroll tabs left"
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3" />
        </button>
      </div>
      <div
        ref={containerRef}
        className="flex flex-nowrap overflow-x-auto no-scrollbar md:space-x-4 scroll-smooth snap-x"
        role="tablist"
        aria-label="Settings tabs"
      >
        {tabs.map((tab, index) => (
          <button
            key={index}
            onClick={() => setActiveTab(tab)}
            className={`snap-start h-9 rounded-3xl px-4 font-bold transition-colors ${
              activeTab === tab
                ? 'bg-neutral-200 text-neutral-900 dark:bg-dark-charcoal dark:text-white'
                : 'text-neutral-700 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-white'
            }`}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`${tab.toLowerCase()}-panel`}
            id={`${tab.toLowerCase()}-tab`}
          >
            {tab}
          </button>
        ))}
      </div>
      <div className="md:hidden z-10">
        <button
          onClick={() => scrollTabs(1)}
          className="flex h-6 w-6 rounded-full items-center justify-center hover:bg-gray-200 dark:hover:bg-gray-700"
          aria-label="Scroll tabs right"
        >
          <img src={ArrowRight} alt="right-arrow" className="h-3" />
        </button>
      </div>
    </div>
  );
};

export default SettingsBar;
