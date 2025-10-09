import './locale/i18n';

import { useState } from 'react';
import { Outlet, Route, Routes } from 'react-router-dom';

import Agents from './agents';
import SharedAgentGate from './agents/SharedAgentGate';
import ActionButtons from './components/ActionButtons';
import Spinner from './components/Spinner';
import UploadToast from './components/UploadToast';
import Conversation from './conversation/Conversation';
import { SharedConversation } from './conversation/SharedConversation';
import { useDarkTheme, useMediaQuery } from './hooks';
import useTokenAuth from './hooks/useTokenAuth';
import Navigation from './Navigation';
import PageNotFound from './PageNotFound';
import Setting from './settings';
import Notification from './components/Notification';

function AuthWrapper({ children }: { children: React.ReactNode }) {
  const { isAuthLoading } = useTokenAuth();

  if (isAuthLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return <>{children}</>;
}

function MainLayout() {
  const { isMobile, isTablet } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!(isMobile || isTablet));

  return (
    <div className="dark:bg-raisin-black relative h-screen overflow-hidden">
      <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />
      <ActionButtons showNewChat={true} showShare={true} />
      <div
        className={`h-[calc(100dvh-64px)] overflow-auto transition-all duration-300 ease-in-out lg:h-screen ${
          !(isMobile || isTablet)
            ? `${navOpen ? 'lg:ml-72' : 'lg:ml-0'}`
            : 'ml-0 lg:ml-16'
        }`}
      >
        <Outlet />
      </div>
      <UploadToast />
    </div>
  );
}
export default function App() {
  const [, , componentMounted] = useDarkTheme();
  const [showNotification, setShowNotification] = useState<boolean>(() => {
    const saved = localStorage.getItem('showNotification');
    return saved ? JSON.parse(saved) : true;
  });
  const notificationText = import.meta.env.VITE_NOTIFICATION_TEXT;
  const notificationLink = import.meta.env.VITE_NOTIFICATION_LINK;
  if (!componentMounted) {
    return <div />;
  }
  return (
    <div className="relative h-full overflow-hidden">
      {notificationLink && notificationText && showNotification && (
        <Notification
          notificationText={notificationText}
          notificationLink={notificationLink}
          handleCloseNotification={() => {
            setShowNotification(false);
            localStorage.setItem('showNotification', 'false');
          }}
        />
      )}
      <Routes>
        <Route
          element={
            <AuthWrapper>
              <MainLayout />
            </AuthWrapper>
          }
        >
          <Route index element={<Conversation />} />
          <Route path="/settings/*" element={<Setting />} />
          <Route path="/agents/*" element={<Agents />} />
        </Route>
        <Route path="/share/:identifier" element={<SharedConversation />} />
        <Route path="/shared/agent/:agentId" element={<SharedAgentGate />} />
        <Route path="/*" element={<PageNotFound />} />
      </Routes>
    </div>
  );
}
