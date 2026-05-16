import React from 'react';

import { useEventStream } from './useEventStream';

/**
 * Mount-once provider that opens the user's SSE connection. Place
 * inside ``AuthWrapper`` so it sees a populated token, and wrap the
 * authenticated-app subtree so the connection lives for the user's
 * whole session.
 */
export function EventStreamProvider({
  children,
}: {
  children: React.ReactNode;
}): React.ReactElement {
  useEventStream();
  return <>{children}</>;
}
