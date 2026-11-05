import { useEffect, useMemo } from 'react';
import { useSelector } from 'react-redux';

import {
  selectApprovalConversations,
  selectFailedConversations,
} from '../activity/activitySlice';
import type { RootState } from '../store';

import { selectUnread } from './backgroundSlice';

const COUNT_PREFIX = /^\(\d+\) /;

/** `title` with `(count) ` in front, or without any count at zero. */
export function titleWithCount(title: string, count: number): string {
  const plain = title.replace(COUNT_PREFIX, '');
  return count > 0 ? `(${count}) ${plain}` : plain;
}

/**
 * Put the number of chats that need the user in front of the tab title,
 * "(2) DocsGPT": a chat with something new, a failure or an approval
 * waiting, the sidebar marks that ask for something, each chat counted once.
 * An unread mark counts while the sidebar lists its chat (all of them before
 * the list loads): one deleted elsewhere, or never listed, has no row to
 * read it from. It drops as those chats are read, and the plain title comes
 * back when none are left or the hook unmounts.
 */
export function useTabTitleCount(): void {
  const unread = useSelector(selectUnread);
  const listed = useSelector(
    (state: RootState) => state.preference.conversations?.data,
  );
  const failed = useSelector(selectFailedConversations);
  const approvals = useSelector(selectApprovalConversations);
  const count = useMemo(() => {
    const listedIds = listed ? new Set(listed.map((chat) => chat.id)) : null;
    const unreadIds = Object.keys(unread).filter(
      (id) => !listedIds || listedIds.has(id),
    );
    return new Set([...unreadIds, ...failed, ...approvals]).size;
  }, [unread, listed, failed, approvals]);

  useEffect(() => {
    document.title = titleWithCount(document.title, count);
    return () => {
      document.title = titleWithCount(document.title, 0);
    };
  }, [count]);
}
