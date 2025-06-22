import React, { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import ArrowLeft from '../assets/arrow-left.svg';
import ArrowRight from '../assets/arrow-right.svg';

type HiddenGradientType = 'left' | 'right' | undefined;

const useTabs = () => {
  const { t } = useTranslation();
  const tabs = [
    t('settings.general.label'),
    t('settings.documents.label'),
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
    <div className="relative mt-6 flex flex-row items-center space-x-1 overflow-auto md:space-x-0">
      <div
        className={`${hiddenGradient === 'left' ? 'hidden' : ''} dark:from-raisin-black pointer-events-none absolute inset-y-0 left-6 w-14 bg-linear-to-r from-white md:hidden`}
      ></div>
      <div
        className={`${hiddenGradient === 'right' ? 'hidden' : ''} dark:from-raisin-black pointer-events-none absolute inset-y-0 right-6 w-14 bg-linear-to-l from-white md:hidden`}
      ></div>

      <div className="z-10 md:hidden">
        <button
          onClick={() => scrollTabs(-1)}
          className="flex h-6 w-6 items-center justify-center rounded-full transition-all hover:bg-gray-200 dark:hover:bg-gray-700"
          aria-label="Scroll tabs left"
        >
          <img src={ArrowLeft} alt="left-arrow" className="h-3" />
        </button>
      </div>
      <div
        ref={containerRef}
        className="no-scrollbar flex snap-x flex-nowrap overflow-x-auto scroll-smooth md:space-x-4"
        role="tablist"
        aria-label="Settings tabs"
      >
        {tabs.map((tab, index) => (
          <button
            key={index}
            onClick={() => setActiveTab(tab)}
            className={`h-9 snap-start rounded-3xl px-4 font-bold transition-colors ${
              activeTab === tab
                ? 'dark:bg-dark-charcoal bg-[#F4F4F5] text-neutral-900 dark:text-white'
                : 'text-neutral-700 hover:text-neutral-900 dark:text-neutral-300 dark:hover:text-white'
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
      <div className="z-10 md:hidden">
        <button
          onClick={() => scrollTabs(1)}
          className="flex h-6 w-6 items-center justify-center rounded-full hover:bg-gray-200 dark:hover:bg-gray-700"
          aria-label="Scroll tabs right"
        >
          <img src={ArrowRight} alt="right-arrow" className="h-3" />
        </button>
      </div>
    </div>
  );
};

export default SettingsBar;
