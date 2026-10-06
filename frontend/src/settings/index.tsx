import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';

import userService from '../api/services/userService';
import { useMediaQuery } from '../hooks';
import { Doc } from '../models/misc';
import SectionIndexPage from '../navigation/SectionIndexPage';
import SectionShell from '../navigation/SectionShell';
import { SETTINGS_SECTION } from '../navigation/sections';
import {
  selectPaginatedDocuments,
  selectSourceDocs,
  selectToken,
  setPaginatedDocuments,
  setSourceDocs,
} from '../preferences/preferenceSlice';
import Analytics from './Analytics';
import Connectors from './Connectors';
import CustomModels from './CustomModels';
import General from './General';
import Logs from './Logs';
import Monitors from '../monitors/Monitors';
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
  const { t } = useTranslation();
  const dispatch = useDispatch();
  const location = useLocation();
  const { isMobile } = useMediaQuery();

  const showIndex = isMobile && location.pathname === SETTINGS_SECTION.rootPath;

  const token = useSelector(selectToken);
  const documents = useSelector(selectSourceDocs);
  const paginatedDocuments = useSelector(selectPaginatedDocuments);

  /**
   * Deletes a source and drops it from both lists by id. Returned to Sources'
   * ConfirmationModal: a refused or failed delete (403 for a role without
   * `delete`) rejects with the message the dialog shows, and leaves the
   * lists alone.
   */
  const handleDeleteClick = async (_index: number, doc: Doc) => {
    const withoutDoc = (list: Doc[]) => list.filter((d) => d.id !== doc.id);
    let response: Response;
    try {
      response = await userService.deletePath(doc.id ?? '', token);
    } catch (error) {
      console.error(error);
      throw new Error(t('settings.sources.errors.delete'));
    }
    if (!response.ok) {
      throw new Error(
        response.status === 403
          ? t('settings.sources.errors.forbidden')
          : t('settings.sources.errors.delete'),
      );
    }
    if (paginatedDocuments) {
      dispatch(setPaginatedDocuments(withoutDoc(paginatedDocuments)));
    }
    if (documents) dispatch(setSourceDocs(withoutDoc(documents)));
  };

  if (showIndex) {
    return (
      <SectionShell header={false}>
        <SectionIndexPage section={SETTINGS_SECTION} />
      </SectionShell>
    );
  }

  return (
    <SectionShell>
      <Routes>
        <Route index element={<General />} />
        <Route path="general" element={<General />} />
        {/* Sources are called Knowledge now; old links keep working. */}
        <Route path="sources" element={<SourcesRedirect />} />
        <Route
          path="knowledge"
          element={
            <Sources
              paginatedDocuments={paginatedDocuments}
              handleDeleteDocument={handleDeleteClick}
            />
          }
        />
        <Route path="analytics" element={<Analytics />} />
        <Route path="logs" element={<Logs />} />
        <Route path="monitors" element={<Monitors />} />
        <Route path="connectors" element={<Connectors />} />
        <Route path="tools" element={<Tools />} />
        <Route
          path="devices"
          element={<Navigate to="/settings/tools" replace />}
        />
        <Route path="custom-models" element={<CustomModels />} />
        <Route path="access-tokens" element={<PersonalAccessTokens />} />
        <Route path="*" element={<Navigate to="/settings" replace />} />
      </Routes>
    </SectionShell>
  );
}

/** `/settings/sources` from before the rename, query string kept. */
function SourcesRedirect() {
  const { search, hash } = useLocation();
  return (
    <Navigate to={{ pathname: '/settings/knowledge', search, hash }} replace />
  );
}
