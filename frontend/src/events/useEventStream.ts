import { useEffect } from 'react';
import { useDispatch, useSelector, useStore } from 'react-redux';

import {
  selectLastEventId,
  sseHealthChanged,
  sseLastEventIdAdvanced,
} from '../notifications/notificationsSlice';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch, RootState } from '../store';

import { connectEventStream } from './eventStreamClient';
import { dispatchSSEEvent } from './dispatchEvent';

/**
 * Open the SSE connection for the current token and keep it alive for
 * the lifetime of the host component. Recreates the connection on
 * token change (login / refresh).
 *
 * The ``lastEventId`` cursor is read lazily from the slice on each
 * connect attempt via ``store.getState()`` — capturing it at mount time
 * would silently re-replay the entire 24h backlog on token rotation,
 * since the slice's id advances during the previous connection's
 * lifetime but a snapshot ref would still hold the value seen at
 * first mount.
 */
export function useEventStream(): void {
  const dispatch = useDispatch<AppDispatch>();
  const token = useSelector(selectToken);
  const store = useStore<RootState>();

  useEffect(() => {
    // Connect even when token is null. Self-hosted dev installs run
    // with ``AUTH_TYPE`` unset, where ``handle_auth`` maps every
    // request to ``{"sub": "local"}`` regardless of headers — gating
    // the connection on a populated token would silently disable push
    // notifications for the most common configuration. When auth IS
    // required and token is null, the backend will 401 and the
    // health state will flip to ``unhealthy`` via the response check
    // inside ``connectEventStream``.
    const conn = connectEventStream({
      token,
      getLastEventId: () => selectLastEventId(store.getState()),
      onEvent: (envelope) => dispatchSSEEvent(envelope, dispatch),
      // Advance the slice cursor for every id-bearing frame. Each tab
      // owns an independent SSE connection and Redux store, so every
      // active tab tracks its own replay cursor.
      onLastEventId: (id) => dispatch(sseLastEventIdAdvanced(id)),
      onHealthChange: (health) => dispatch(sseHealthChanged(health)),
    });

    return () => {
      conn.close();
    };
  }, [token, dispatch, store]);
}
