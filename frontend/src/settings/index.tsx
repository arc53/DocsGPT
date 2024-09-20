import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import ArrowLeft from '../assets/arrow-left.svg';
import ArrowRight from '../assets/arrow-right.svg';
import i18n from '../locale/i18n';
import { Doc } from '../models/misc';
import {
  selectSourceDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Analytics from './Analytics';
import APIKeys from './APIKeys';
import Documents from './Documents';
import General from './General';
import Logs from './Logs';
import Widgets from './Widgets';

export default function Settings() {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const tabs = [
    t('settings.general.label'),
    t('settings.documents.label'),
    t('settings.apiKeys.label'),
    t('settings.analytics.label'),
    t('settings.logs.label'),
  ];
  const [activeTab, setActiveTab] = React.useState(t('settings.general.label'));
  const [widgetScreenshot, setWidgetScreenshot] = React.useState<File | null>(
    null,
  );

  const documents = useSelector(selectSourceDocs);
  const updateWidgetScreenshot = (screenshot: File | null) => {
    setWidgetScreenshot(screenshot);
  };

  const handleDeleteClick = (index: number, doc: Doc) => {
    userService
      .deletePath(doc.id ?? '')
      .then((response) => {
        if (response.ok && documents) {
          const updatedDocuments = [
            ...documents.slice(0, index),
            ...documents.slice(index + 1),
          ];
          dispatch(setSourceDocs(updatedDocuments));
        }
      })
      .catch((error) => console.error(error));
  };

  React.useEffect(() => {
    setActiveTab(t('settings.general.label'));
  }, [i18n.language]);
  return (
    <div className="p-4 md:p-12 h-full overflow-auto">
      <p className="text-2xl font-bold text-eerie-black dark:text-bright-gray">
        {t('settings.label')}
      </p>
      <div className="mt-6 flex flex-row items-center space-x-4 overflow-auto md:space-x-8 ">
        <div className="md:hidden">
          <button
            onClick={() => scrollTabs(-1)}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-purple-30 transition-all hover:bg-gray-100"
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-6 w-6" />
          </button>
        </div>
        <div className="flex flex-nowrap space-x-4 overflow-x-auto no-scrollbar md:space-x-8">
          {tabs.map((tab, index) => (
            <button
              key={index}
              onClick={() => setActiveTab(tab)}
              className={`h-9 rounded-3xl px-4 font-bold ${
                activeTab === tab
                  ? 'bg-purple-3000 text-purple-30 dark:bg-dark-charcoal'
                  : 'text-gray-6000'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="md:hidden">
          <button
            onClick={() => scrollTabs(1)}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-purple-30 hover:bg-gray-100"
          >
            <img src={ArrowRight} alt="right-arrow" className="h-6 w-6" />
          </button>
        </div>
      </div>
      {renderActiveTab()}

      {/* {activeTab === 'Widgets' && (
        <Widgets
          widgetScreenshot={widgetScreenshot}
          onWidgetScreenshotChange={updateWidgetScreenshot}
        />
      )} */}
    </div>
  );

  function scrollTabs(direction: number) {
    const container = document.querySelector('.flex-nowrap');
    if (container) {
      container.scrollLeft += direction * 100; // Adjust the scroll amount as needed
    }
  }

  function renderActiveTab() {
    switch (activeTab) {
      case t('settings.general.label'):
        return <General />;
      case t('settings.documents.label'):
        return (
          <Documents
            documents={documents}
            handleDeleteDocument={handleDeleteClick}
          />
        );
      case 'Widgets':
        return (
          <Widgets
            widgetScreenshot={widgetScreenshot} // Add this line
            onWidgetScreenshotChange={updateWidgetScreenshot} // Add this line
          />
        );
      case t('settings.apiKeys.label'):
        return <APIKeys />;
      case t('settings.analytics.label'):
        return <Analytics />;
      case t('settings.logs.label'):
        return <Logs />;
      default:
        return null;
    }
  }
}
