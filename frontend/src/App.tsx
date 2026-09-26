import { envVar } from '@/env';
import './locale/i18n';

import { lazy, Suspense, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelector } from 'react-redux';
import { Outlet, Route, Routes, useLocation } from 'react-router-dom';

import { cn } from '@/lib/utils';

import Admin from './admin';
import Agents from './agents';
import SharedAgentGate from './agents/SharedAgentGate';
import { selectWorkflowPreviewOpen } from './agents/workflow/workflowPreviewSlice';
import DocsGPTMark from './assets/logo-b.svg';
import DocsGPTMarkWhite from './assets/logo-w.svg';
import ActionButtons from './components/ActionButtons';
import AdminRoute from './components/AdminRoute';
import ErrorBoundary from './components/ErrorBoundary';
import { LoadingState } from '@/components/ui/loading-state';
import { Button } from './components/ui/button';
import { ToastViewport } from './components/ui/toast';
import UploadToast from './components/UploadToast';
import Conversation from './conversation/Conversation';
import { SharedConversation } from './conversation/SharedConversation';
import { EventStreamProvider } from './events/EventStreamProvider';
import { useDarkTheme, useMediaQuery } from './hooks';
import useDataInitializer from './hooks/useDataInitializer';
import useTokenAuth from './hooks/useTokenAuth';
import Navigation from './Navigation';
import { getSectionForPath } from './navigation/sections';
import { SidebarLevelProvider } from './navigation/SidebarLevelProvider';
import PageNotFound from './PageNotFound';

// Dev-only style guide (see frontend/DESIGN.md). The DEV guard around the
// import lets the bundler drop the chunk from production builds entirely.
const DesignSystem = import.meta.env.DEV
  ? lazy(() => import('./design/DesignSystem'))
  : null;
import Setting from './settings';
import Teams from './settings/Teams';
import Notification from './components/Notification';
import ToolApprovalToast from './notifications/ToolApprovalToast';
import TeamNotificationToast from './notifications/TeamNotificationToast';
import ActionToast from './notifications/ActionToast';

function AuthWrapper({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const {
    isAuthLoading,
    oidcFailed,
    oidcErrorCode,
    oidcProviderName,
    retryOidcLogin,
  } = useTokenAuth();
  useDataInitializer(isAuthLoading);
  const [isDarkTheme] = useDarkTheme();

  if (oidcFailed) {
    const message =
      oidcErrorCode === 'not_authorized'
        ? t('auth.notAuthorized')
        : oidcErrorCode === 'account_disabled'
          ? t('auth.accountDisabled')
          : t('auth.signInToContinue');
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-6">
        <img
          src={isDarkTheme ? DocsGPTMarkWhite : DocsGPTMark}
          alt="DocsGPT"
          className="h-14 w-auto"
        />
        <p className="text-foreground max-w-md px-6 text-center text-sm">
          {message}
        </p>
        <Button
          type="button"
          onClick={retryOidcLogin}
          shape="pill"
          data-testid="oidc-signin"
        >
          {t('auth.signInWith', { provider: oidcProviderName || 'SSO' })}
        </Button>
      </div>
    );
  }
  if (isAuthLoading) {
    return <LoadingState fill="screen" />;
  }
  return <EventStreamProvider>{children}</EventStreamProvider>;
}

function MainLayout() {
  const { isMobile } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!isMobile);
  const location = useLocation();
  // Settings and admin pages keep the profile menu but drop the chat actions:
  // the conversation now survives the trip, so "share" would target a chat
  // that isn't on screen.
  const inSection = Boolean(getSectionForPath(location.pathname));
  // The workflow Preview drawer occupies the right edge; move the toast
  // stack to the bottom-left while it's open so it stays visible without
  // covering the drawer's attach/send controls.
  const previewOpen = useSelector(selectWorkflowPreviewOpen);

  return (
    <SidebarLevelProvider>
      <div className="bg-background relative h-dvh overflow-hidden">
        <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />
        <ActionButtons showShare={!inSection} />
        <div
          className={cn(
            'h-[calc(100dvh-56px)] overflow-auto transition-[margin] duration-300 ease-in-out lg:h-dvh',
            !isMobile ? (navOpen ? 'lg:ml-72' : 'lg:ml-14') : 'ml-0 lg:ml-16',
          )}
        >
          {/* Contain route render crashes so navigation stays usable;
            keyed by path so the boundary resets when the user leaves. */}
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
        {/* The one toast stack (and live region) for the app. Each toast
          renders only its cards, top to bottom: team notifications, tool
          approvals, uploads, action results. */}
        <ToastViewport
          className={cn(previewOpen && 'right-auto left-4')}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <TeamNotificationToast />
          <ToolApprovalToast />
          <UploadToast />
          <ActionToast />
        </ToastViewport>
      </div>
    </SidebarLevelProvider>
  );
}
export default function App() {
  const [, , componentMounted] = useDarkTheme();
  const location = useLocation();
  const [showNotification, setShowNotification] = useState<boolean>(() => {
    const saved = localStorage.getItem('showNotification');
    return saved ? JSON.parse(saved) : true;
  });
  const notificationText = envVar('VITE_NOTIFICATION_TEXT');
  const notificationLink = envVar('VITE_NOTIFICATION_LINK');
  // Hide the changelog banner on public share routes — those pages are
  // embedded / shared externally and shouldn't carry product chrome.
  const isPublicShareRoute =
    location.pathname.startsWith('/share/') ||
    location.pathname.startsWith('/shared/');
  if (!componentMounted) {
    return <div />;
  }
  return (
    <div className="relative h-full overflow-hidden">
      {notificationLink &&
        notificationText &&
        showNotification &&
        !isPublicShareRoute && (
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
          {/* One dynamic route (accepting "new" or a UUID) so the
              /c/new → /c/<id> replace doesn't remount Conversation. */}
          <Route path="/c/:conversationId" element={<Conversation />} />
          <Route
            path="/agents/:agentId/c/:conversationId"
            element={<Conversation />}
          />
          <Route path="/settings/*" element={<Setting />} />
          <Route path="/teams" element={<Teams />} />
          <Route path="/agents/*" element={<Agents />} />
          <Route
            path="/admin/*"
            element={
              <AdminRoute>
                <Admin />
              </AdminRoute>
            }
          />
        </Route>
        <Route path="/share/:identifier" element={<SharedConversation />} />
        <Route path="/shared/agent/:agentId" element={<SharedAgentGate />} />
        {DesignSystem && (
          <Route
            path="/design"
            element={
              <Suspense fallback={null}>
                <DesignSystem />
              </Suspense>
            }
          />
        )}
        <Route path="/*" element={<PageNotFound />} />
      </Routes>
    </div>
  );
}
