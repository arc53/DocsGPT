import { useDispatch, useSelector } from 'react-redux';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import userService from '../api/services/userService';
import { useMediaQuery } from '../hooks';
import { Doc } from '../models/misc';
import SectionIndexPage from '../navigation/SectionIndexPage';
import SectionPageHeader from '../navigation/SectionPageHeader';
import { getActiveItem, SETTINGS_SECTION } from '../navigation/sections';
import {
  selectPaginatedDocuments,
  selectSourceDocs,
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Analytics from './Analytics';
import CustomModels from './CustomModels';
import General from './General';
import Logs from './Logs';
import PersonalAccessTokens from './PersonalAccessTokens';
import Sources from './Sources';
import Tools from './Tools';

/**
 * Settings shell. The section's destinations live in the sidebar
 * (see `navigation/SectionNav`), so this only renders the active page and
 * its title — except below `lg`, where the sidebar is an overlay and
 * `/settings` shows the destination list as page content instead.
 */
export default function Settings() {
  const dispatch = useDispatch();
  const location = useLocation();
  const { isMobile, isTablet } = useMediaQuery();

  const activeItem = getActiveItem(SETTINGS_SECTION, location.pathname);
  const showIndex =
    (isMobile || isTablet) && location.pathname === SETTINGS_SECTION.rootPath;

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
      <div className="mx-auto w-full max-w-6xl">
        {showIndex ? (
          <SectionIndexPage section={SETTINGS_SECTION} />
        ) : (
          <>
            <SectionPageHeader section={SETTINGS_SECTION} item={activeItem} />
            <Routes>
              <Route index element={<General />} />
              <Route path="general" element={<General />} />
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
              <Route
                path="devices"
                element={<Navigate to="/settings/tools" replace />}
              />
              <Route path="custom-models" element={<CustomModels />} />
              <Route path="access-tokens" element={<PersonalAccessTokens />} />
              <Route path="*" element={<Navigate to="/settings" replace />} />
            </Routes>
          </>
        )}
      </div>
    </div>
  );
}
