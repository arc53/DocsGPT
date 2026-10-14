import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { usePageVisible } from '../backgroundJobs/usePageVisible';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import { loadActivityNow } from './activitySlice';

/**
 * A slow refresh while the tab is visible. Events keep the snapshot current;
 * this only catches what they can't say, such as an answer whose stream died
 * without ending.
 */
export const ACTIVITY_REFRESH_MS = 60_000;

/**
 * Keeps the Activity snapshot loaded for the whole app: the sidebar's marks
 * and count read it. Loads per token and when the tab comes back into view;
 * `activityListenerMiddleware` refetches after the events that change it.
 */
export default function useActivityLoader(): void {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const visible = usePageVisible();

  useEffect(() => {
    if (!visible) return;
    void dispatch(loadActivityNow('poll'));
    const timer = window.setInterval(
      () => void dispatch(loadActivityNow('poll')),
      ACTIVITY_REFRESH_MS,
    );
    return () => window.clearInterval(timer);
  }, [dispatch, token, visible]);
}
