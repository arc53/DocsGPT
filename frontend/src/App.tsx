import './locale/i18n';

import { useState } from 'react';
import { Outlet, Route, Routes } from 'react-router-dom';

import About from './About';
import Spinner from './components/Spinner';
import Conversation from './conversation/Conversation';
import { SharedConversation } from './conversation/SharedConversation';
import { useDarkTheme, useMediaQuery } from './hooks';
import useTokenAuth from './hooks/useTokenAuth';
import Navigation from './Navigation';
import PageNotFound from './PageNotFound';
import Setting from './settings';

function AuthWrapper({ children }: { children: React.ReactNode }) {
  const { isAuthLoading } = useTokenAuth();

  if (isAuthLoading) {
    return (
      <div className="h-screen flex items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}

function MainLayout() {
  const { isMobile } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!isMobile);

  return (
    <div className="dark:bg-raisin-black relative h-screen overflow-auto">
      <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />
      <div
        className={`h-[calc(100dvh-64px)] md:h-screen ${
          !isMobile
            ? `ml-0 ${!navOpen ? 'md:mx-auto lg:mx-auto' : 'md:ml-72'}`
            : 'ml-0 md:ml-16'
        }`}
      >
        <Outlet />
      </div>
    </div>
  );
}

export default function App() {
  const [, , componentMounted] = useDarkTheme();
  if (!componentMounted) {
    return <div />;
  }
  return (
    <div className="h-full relative overflow-auto">
      <Routes>
        <Route
          element={
            <AuthWrapper>
              <MainLayout />
            </AuthWrapper>
          }
        >
          <Route index element={<Conversation />} />
          <Route path="/about" element={<About />} />
          <Route path="/settings" element={<Setting />} />
        </Route>
        <Route path="/share/:identifier" element={<SharedConversation />} />
        <Route path="/*" element={<PageNotFound />} />
      </Routes>
    </div>
  );
}
