import { createContext, useContext } from 'react';

import type { Crumb } from './PathHeader';

/**
 * The Knowledge folder a source was opened in, as crumbs (top-level folder
 * first), so its view's header reads `Knowledge › Carriers › source › …` and
 * each folder crumb returns to that folder. Empty outside a folder.
 */
export const SourceFolderTrail = createContext<Crumb[]>([]);

/** The folder crumbs a source view puts after its Knowledge crumb. */
export const useSourceFolderTrail = (): Crumb[] =>
  useContext(SourceFolderTrail);
