import React, { useCallback, useRef, useState } from 'react';
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
import ArrowLeft from '../assets/arrow-left.svg';
import ArrowRight from '../assets/arrow-right.svg';
import { Button } from '../components/ui/button';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';
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
import CustomModels from './CustomModels';
import Sources from './Sources';
import General from './General';
import Logs from './Logs';
import Tools from './Tools';

type HiddenGradientType = 'left' | 'right' | undefined;

export default function Settings() {
  const dispatch = useDispatch();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();

  const getActiveTabFromPath = () => {
    const path = location.pathname;
    if (path.includes('/settings/sources')) return t('settings.sources.label');
    if (path.includes('/settings/analytics'))
      return t('settings.analytics.label');
    if (path.includes('/settings/logs')) return t('settings.logs.label');
    if (path.includes('/settings/tools')) return t('settings.tools.label');
    if (path.includes('/settings/custom-models'))
      return t('settings.customModels.label');
    return t('settings.general.label');
  };

  const [activeTab, setActiveTab] = React.useState(getActiveTabFromPath());
  const tabsList = [
    t('settings.general.label'),
    t('settings.sources.label'),
    t('settings.analytics.label'),
    t('settings.logs.label'),
    t('settings.tools.label'),
    t('settings.customModels.label'),
  ];
  const [hiddenGradient, setHiddenGradient] =
    useState<HiddenGradientType>('left');
  const containerRef = useRef<null | HTMLDivElement>(null);

  const scrollTabs = useCallback(
    (direction: number) => {
      if (containerRef.current) {
        const container = containerRef.current;
        container.scrollLeft += direction * 100;
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
    [containerRef],
  );

  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === t('settings.general.label')) navigate('/settings');
    else if (tab === t('settings.sources.label')) navigate('/settings/sources');
    else if (tab === t('settings.analytics.label'))
      navigate('/settings/analytics');
    else if (tab === t('settings.logs.label')) navigate('/settings/logs');
    else if (tab === t('settings.tools.label')) navigate('/settings/tools');
    else if (tab === t('settings.customModels.label'))
      navigate('/settings/custom-models');
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
      <p className="text-foreground dark:text-foreground text-2xl font-bold">
        {t('settings.label')}
      </p>
      <Tabs
        value={activeTab}
        onValueChange={(tab) => handleTabChange(tab)}
        className="relative mt-6 flex flex-row items-center space-x-1 overflow-auto md:space-x-0"
      >
        <div
          className={`${hiddenGradient === 'left' ? 'hidden' : ''} dark:from-background pointer-events-none absolute inset-y-0 left-6 w-14 bg-linear-to-r from-white md:hidden`}
        ></div>
        <div
          className={`${hiddenGradient === 'right' ? 'hidden' : ''} dark:from-background pointer-events-none absolute inset-y-0 right-6 w-14 bg-linear-to-l from-white md:hidden`}
        ></div>
        <div className="z-10 md:hidden">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => scrollTabs(-1)}
            className="hover:bg-muted dark:hover:bg-accent h-6 w-6 rounded-full"
            aria-label={t('settings.scrollTabsLeft')}
          >
            <img src={ArrowLeft} alt="left-arrow" className="h-3" />
          </Button>
        </div>
        <TabsList ref={containerRef} aria-label={t('settings.tabsAriaLabel')}>
          {tabsList.map((tab) => (
            <TabsTrigger key={tab} value={tab}>
              {tab}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="z-10 md:hidden">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={() => scrollTabs(1)}
            className="hover:bg-muted dark:hover:bg-accent h-6 w-6 rounded-full"
            aria-label={t('settings.scrollTabsRight')}
          >
            <img src={ArrowRight} alt="right-arrow" className="h-3" />
          </Button>
        </div>
      </Tabs>
      <Routes>
        <Route index element={<General />} />
        <Route
          path="sources"
          element={
            <Sources
              paginatedDocuments={paginatedDocuments}
              handleDeleteDocument={handleDeleteClick}
            />
          }
        />
        <Route path="analytics" element={<Analytics />} />
        <Route path="logs" element={<Logs />} />
        <Route path="tools" element={<Tools />} />
        <Route path="custom-models" element={<CustomModels />} />
        <Route path="*" element={<Navigate to="/settings" replace />} />
      </Routes>
    </div>
  );
}
