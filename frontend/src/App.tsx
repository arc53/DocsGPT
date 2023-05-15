import { useState } from 'react';
import { ActiveState } from './models/misc';
import { inject } from '@vercel/analytics';
import Login from './Login';
import { ClerkProvider, SignedIn, SignedOut } from '@clerk/clerk-react';
import QueryPage from './QueryPage';

inject();

if (!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY) {
  throw 'Missing Publishable Key';
}

const clerkPubKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

export default function App() {
  //TODO : below media query is disjoint from tailwind. Please wire it together.
  const [navState, setNavState] = useState<ActiveState>(
    window.matchMedia('(min-width: 768px)').matches ? 'ACTIVE' : 'INACTIVE',
  );

  return (
    <ClerkProvider publishableKey={clerkPubKey}>
      <SignedIn>
        <QueryPage />
      </SignedIn>
      <SignedOut>
        <Login />
      </SignedOut>
    </ClerkProvider>
  );
}
