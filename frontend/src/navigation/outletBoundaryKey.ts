import { matchPath } from 'react-router-dom';

/** The routes that render Conversation (App.tsx). */
const CHAT_ROUTES = [
  '/',
  '/c/:conversationId',
  '/agents/:agentId/c/:conversationId',
];

/**
 * The key for the error boundary around the routed page. Chat routes share
 * one: Conversation follows the URL itself, and opening a chat loads it
 * before the URL changes, so a path key would mount it a second time.
 */
export function outletBoundaryKey(pathname: string): string {
  return CHAT_ROUTES.some((pattern) => matchPath(pattern, pathname))
    ? 'chat'
    : pathname;
}
