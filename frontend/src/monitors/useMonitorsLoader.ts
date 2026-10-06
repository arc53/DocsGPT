import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';

import { selectToken } from '@/preferences/preferenceSlice';
import type { AppDispatch } from '@/store';

import { loadMonitors, selectMonitorsState } from './monitorsSlice';

/**
 * Loads the user's monitors once per session token, so conversations with an
 * active monitor show the "watching" mark; `monitor.updated` events keep it
 * current after that.
 */
export default function useMonitorsLoader(): void {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const { loading } = useSelector(selectMonitorsState);

  useEffect(() => {
    // Once per token: events keep the list current between loads.
    if (!loading) void dispatch(loadMonitors({ token }));
  }, [dispatch, token]);
}
