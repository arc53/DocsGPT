import React from 'react';

// Layout timing in the browser, without React's warning on the server.
export const useClientLayoutEffect =
  typeof window === 'undefined' ? React.useEffect : React.useLayoutEffect;
