import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import General from './General';
import Documents from './Documents';
import APIKeys from './APIKeys';
import Widgets from './Widgets';
import {
  selectSourceDocs,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import { Doc } from '../preferences/preferenceApi';
import ArrowLeft from '../assets/arrow-left.svg';
import ArrowRight from '../assets/arrow-right.svg';
import { useTranslation } from 'react-i18next';

const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';

const Settings: React.FC = () => {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const tabs = [
    t('settings.general.label'),
    t('settings.documents.label'),
    t('settings.apiKeys.label'),
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
    const docPath = 'indexes/' + 'local' + '/' + doc.name;
    fetch(`${apiHost}/api/delete_old?path=${docPath}`, {
      method: 'GET',
    })
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
  return (
    <div className="wa p-4 pt-20 md:p-12">
      <p className="text-2xl font-bold text-eerie-black dark:text-bright-gray">
        {t('settings.label')}
      </p>
      <div className="mt-6 flex flex-row items-center space-x-4 overflow-x-auto md:space-x-8 ">
        <div className="md:hidden">
          <button
            onClick={() => scrollTabs(-1)}
            className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-purple-30 transition-all hover:bg-gray-100"
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-6 w-6" />
          </button>
        </div>
        <div className="flex flex-nowrap space-x-4 overflow-x-auto md:space-x-8">
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
      default:
        return null;
    }
  }
};

export default Settings;
