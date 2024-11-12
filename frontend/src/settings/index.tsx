import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';

import userService from '../api/services/userService';
import SettingsBar from '../components/SettingsBar';
import i18n from '../locale/i18n';
import { Doc } from '../models/misc';
import {
  selectSourceDocs,
  selectPaginatedDocuments,
  setPaginatedDocuments,
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
  const [activeTab, setActiveTab] = React.useState(t('settings.general.label'));
  const [widgetScreenshot, setWidgetScreenshot] = React.useState<File | null>(
    null,
  );

  const documents = useSelector(selectSourceDocs);
  const paginatedDocuments = useSelector(selectPaginatedDocuments);
  const updateWidgetScreenshot = (screenshot: File | null) => {
    setWidgetScreenshot(screenshot);
  };

  const updateDocumentsList = (documents: Doc[], index: number) => [
    ...documents.slice(0, index),
    ...documents.slice(index + 1),
  ];

  const handleDeleteClick = (index: number, doc: Doc) => {
    userService
      .deletePath(doc.id ?? '')
      .then((response) => {
        if (response.ok && documents) {
          if (paginatedDocuments) {
            dispatch(
              setPaginatedDocuments(
                updateDocumentsList(paginatedDocuments, index),
              ),
            );
          }
          dispatch(setSourceDocs(updateDocumentsList(documents, index)));
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
      <SettingsBar activeTab={activeTab} setActiveTab={setActiveTab} />
      {renderActiveTab()}

      {/* {activeTab === 'Widgets' && (
        <Widgets
          widgetScreenshot={widgetScreenshot}
          onWidgetScreenshotChange={updateWidgetScreenshot}
        />
      )} */}
    </div>
  );

  function renderActiveTab() {
    switch (activeTab) {
      case t('settings.general.label'):
        return <General />;
      case t('settings.documents.label'):
        return (
          <Documents
            paginatedDocuments={paginatedDocuments}
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
