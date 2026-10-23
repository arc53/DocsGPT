import { useSelector } from 'react-redux';

import { selectGraphBuilds } from '../../settings/graphBuildSlice';

export interface GraphBuildProgress {
  /** A graph extraction for the source is running (`graph.extract.progress`). */
  building: boolean;
  /** How far it is, 0–100, or null before it knows how many chunks it has. */
  pct: number | null;
}

/**
 * A source's running graph build, from the extraction events the SSE stream
 * records (graphBuildSlice): the same reading as the Knowledge card's
 * "Building graph… N%" badge.
 *
 * @param sourceId The source; none reads as no build.
 * @returns Whether a build runs and its percentage.
 */
export default function useGraphBuild(sourceId?: string): GraphBuildProgress {
  const builds = useSelector(selectGraphBuilds);
  const build = sourceId ? builds?.[sourceId] : undefined;
  const building = build?.status === 'building';
  const pct =
    building && build.total > 0
      ? Math.min(100, Math.round((build.current / build.total) * 100))
      : null;
  return { building, pct };
}
