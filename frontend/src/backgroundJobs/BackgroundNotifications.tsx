import { useEffect, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useLocation, useNavigate } from 'react-router-dom';

import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';

import { conversationIdFromPath } from './backgroundListener';
import {
  fetchPushConfig,
  markConversationRead,
  selectPushConfig,
  selectUnread,
} from './backgroundSlice';
import ConversationNotificationToast from './ConversationNotificationToast';
import PushPermissionToast from './PushPermissionToast';
import { usePageVisible } from './usePageVisible';
import { usePresence } from './usePresence';
import {
  ensurePushSubscription,
  isPushSupported,
  NAVIGATE_MESSAGE,
  notificationPermission,
  safeAppPath,
} from './webPush';

/**
 * Everything notifications need in the signed-in app, mounted once inside
 * the shared `ToastViewport`: presence reporting, the Web Push setup for a
 * browser that already allowed it, routing a clicked notification, clearing
 * the unread mark of the conversation on screen, and the two toasts.
 */
export default function BackgroundNotifications() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const token = useSelector(selectToken);
  const pushConfig = useSelector(selectPushConfig);
  const unread = useSelector(selectUnread);
  const visible = usePageVisible();
  const subscribedFor = useRef<string | null>(null);

  usePresence();

  useEffect(() => {
    void dispatch(fetchPushConfig());
  }, [dispatch, token]);

  // A browser that already allowed notifications: keep its subscription
  // current (new key, other user signed in). Never asks for permission.
  useEffect(() => {
    const key = pushConfig?.enabled ? pushConfig.public_key : null;
    if (!key || notificationPermission() !== 'granted') return;
    const marker = `${key}:${token ?? ''}`;
    if (subscribedFor.current === marker) return;
    subscribedFor.current = marker;
    ensurePushSubscription(key, token).catch(() => {
      subscribedFor.current = null;
    });
  }, [pushConfig, token]);

  // A clicked notification asks an open tab to route in place.
  useEffect(() => {
    if (!isPushSupported()) return;
    const onMessage = (event: MessageEvent) => {
      const data = event.data as { type?: string; url?: unknown } | null;
      if (data?.type !== NAVIGATE_MESSAGE) return;
      const path = safeAppPath(data.url);
      if (path) navigate(path);
    };
    navigator.serviceWorker.addEventListener('message', onMessage);
    return () =>
      navigator.serviceWorker.removeEventListener('message', onMessage);
  }, [navigate]);

  // The conversation on screen is read.
  const onScreen = conversationIdFromPath(pathname);
  const onScreenUnread = Boolean(onScreen && unread[onScreen]);
  useEffect(() => {
    if (visible && onScreen && onScreenUnread) {
      void dispatch(markConversationRead(onScreen));
    }
  }, [visible, onScreen, onScreenUnread, dispatch]);

  return (
    <>
      <PushPermissionToast />
      <ConversationNotificationToast />
    </>
  );
}
