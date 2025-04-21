import React from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';

import userService from '../api/services/userService';
import SettingsBar from '../components/SettingsBar';
import i18n from '../locale/i18n';
import { Doc } from '../models/misc';
import {
  selectPaginatedDocuments,
  selectSourceDocs,
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Analytics from './Analytics';
import Documents from './Documents';
import General from './General';
import Logs from './Logs';
import Tools from './Tools';
import Widgets from './Widgets';

export default function Settings() {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [widgetScreenshot, setWidgetScreenshot] = React.useState<File | null>(
    null,
  );

  const getActiveTabFromPath = () => {
    const path = location.pathname;
    if (path.includes('/settings/documents'))
      return t('settings.documents.label');
    if (path.includes('/settings/analytics'))
      return t('settings.analytics.label');
    if (path.includes('/settings/logs')) return t('settings.logs.label');
    if (path.includes('/settings/tools')) return t('settings.tools.label');
    if (path.includes('/settings/widgets')) return 'Widgets';
    return t('settings.general.label');
  };

  const [activeTab, setActiveTab] = React.useState(getActiveTabFromPath());

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === t('settings.general.label')) navigate('/settings');
    else if (tab === t('settings.documents.label'))
      navigate('/settings/documents');
    else if (tab === t('settings.analytics.label'))
      navigate('/settings/analytics');
    else if (tab === t('settings.logs.label')) navigate('/settings/logs');
    else if (tab === t('settings.tools.label')) navigate('/settings/tools');
    else if (tab === 'Widgets') navigate('/settings/widgets');
  };

  React.useEffect(() => {
    setActiveTab(getActiveTabFromPath());
  }, [location.pathname]);

  React.useEffect(() => {
    const newActiveTab = getActiveTabFromPath();
    setActiveTab(newActiveTab);
  }, [i18n.language]);

  const token = useSelector(selectToken);
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
      .deletePath(doc.id ?? '', token)
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

  return (
    <div className="h-full overflow-auto p-4 md:p-12">
      <p className="text-2xl font-bold text-eerie-black dark:text-bright-gray">
        {t('settings.label')}
      </p>
      <SettingsBar
        activeTab={activeTab}
        setActiveTab={(tab) => handleTabChange(tab as string)}
      />
      <Routes>
        <Route index element={<General />} />
        <Route
          path="documents"
          element={
            <Documents
              paginatedDocuments={paginatedDocuments}
              handleDeleteDocument={handleDeleteClick}
            />
          }
        />
        <Route path="analytics" element={<Analytics />} />
        <Route path="logs" element={<Logs />} />
        <Route path="tools" element={<Tools />} />
        <Route
          path="widgets"
          element={
            <Widgets
              widgetScreenshot={widgetScreenshot}
              onWidgetScreenshotChange={updateWidgetScreenshot}
            />
          }
        />
        <Route path="*" element={<Navigate to="/settings" replace />} />
      </Routes>
    </div>
  );
}
