import { Routes, Route } from 'react-router-dom';
import { ReactElement, useEffect } from 'react';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import About from './About';
import PageNotFound from './PageNotFound';
import { inject } from '@vercel/analytics';
import { useMediaQuery } from './hooks';
import { useState } from 'react';
import Setting from './settings';
import './locale/i18n';
import SharedConversation from './conversation/SharedConversation';
import { useDarkTheme } from './hooks';
inject();

function MainLayout({ children }: { children: ReactElement }) {
  const { isMobile } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!isMobile);
  return (
    <div className="dark:bg-raisin-black">
      <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />
      <div
        className={`min-h-screen ${
          !isMobile
            ? `ml-0 ${!navOpen ? 'md:mx-auto lg:mx-auto' : 'md:ml-72'}`
            : 'ml-0 md:ml-16'
        }`}
      >
        {children}
      </div>
    </div>
  );
}

function Layout({ children }: { children: ReactElement }) {
  return <div className="h-full dark:bg-raisin-black">{children}</div>;
}
export default function App() {
  const [isDarkTheme] = useDarkTheme();
  useEffect(() => {
    localStorage.setItem('selectedTheme', isDarkTheme ? 'Dark' : 'Light');
    if (isDarkTheme) {
      document
        .getElementById('root')
        ?.classList.add('dark', 'dark:bg-raisin-black');
    } else {
      document.getElementById('root')?.classList.remove('dark');
    }
  }, [isDarkTheme]);
  return (
    <>
      <Routes>
        <Route
          path="/"
          element={
            <MainLayout>
              <Conversation />
            </MainLayout>
          }
        />
        <Route
          path="/about"
          element={
            <MainLayout>
              <About />
            </MainLayout>
          }
        />
        <Route
          path="/settings"
          element={
            <MainLayout>
              <Setting />
            </MainLayout>
          }
        />
        <Route
          path="/share/:identifier"
          element={
            <Layout>
              <SharedConversation />
            </Layout>
          }
        />
        {/* default page */}
        <Route
          path="/*"
          element={
            <Layout>
              <PageNotFound />
            </Layout>
          }
        />
      </Routes>
    </>
  );
}
