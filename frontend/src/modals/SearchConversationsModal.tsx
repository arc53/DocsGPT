import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import SearchIcon from '../assets/search.svg';
import { searchConversations } from '../preferences/preferenceApi';
import WrapperModal from './WrapperModal';

type ConversationListItem = {
  id: string;
  name: string;
  match_field?: 'name' | 'prompt' | 'response' | null;
  match_snippet?: string | null;
};

type SearchConversationsModalProps = {
  close: () => void;
  conversations: ConversationListItem[];
  token: string | null;
  onSelectConversation: (id: string) => void;
};

// Escape regex metacharacters so the user query can be used in a RegExp.
function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const trimmed = query.trim();
  if (!trimmed) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(trimmed)})`, 'gi'));
  return (
    <>
      {parts.map((part, idx) =>
        part.toLowerCase() === trimmed.toLowerCase() ? (
          <mark
            key={idx}
            className="bg-transparent font-semibold text-purple-30"
          >
            {part}
          </mark>
        ) : (
          <span key={idx}>{part}</span>
        ),
      )}
    </>
  );
}

export default function SearchConversationsModal({
  close,
  conversations,
  token,
  onSelectConversation,
}: SearchConversationsModalProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ConversationListItem[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      setIsSearching(false);
      return;
    }
    setIsSearching(true);
    const handle = setTimeout(() => {
      searchConversations(trimmed, token).then((result) => {
        setResults(result.data ?? []);
        setIsSearching(false);
      });
    }, 300);
    return () => clearTimeout(handle);
  }, [query, token]);

  const visibleConversations = useMemo(() => {
    if (!query.trim()) return conversations;
    return results ?? [];
  }, [query, results, conversations]);

  const handleSelect = (id: string) => {
    onSelectConversation(id);
    close();
  };

  const showEmptyState =
    !!query.trim() && !isSearching && visibleConversations.length === 0;

  return (
    <WrapperModal
      close={close}
      className="w-[92vw] max-w-xl p-0"
      contentClassName="max-h-[70vh]"
    >
      <div className="flex flex-col">
        <div className="border-sidebar-border flex items-center gap-2 border-b px-5 py-4">
          <img src={SearchIcon} alt="search" className="h-4 w-4 opacity-60" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('modals.searchConversations.searchPlaceholder')}
            className="text-foreground placeholder:text-muted-foreground w-full bg-transparent text-sm outline-none"
          />
        </div>

        <div className="max-h-[55vh] overflow-y-auto py-2">
          {isSearching && (
            <div className="text-muted-foreground px-5 py-3 text-xs">
              {t('modals.searchConversations.loading')}
            </div>
          )}
          {showEmptyState && (
            <div className="text-muted-foreground px-5 py-3 text-xs">
              {t('modals.searchConversations.noResults')}
            </div>
          )}
          {!isSearching &&
            visibleConversations.map((conversation) => {
              const trimmedQuery = query.trim();
              const showSnippet =
                !!trimmedQuery &&
                !!conversation.match_snippet &&
                conversation.match_field !== 'name';
              return (
                <button
                  key={conversation.id}
                  type="button"
                  onClick={() => handleSelect(conversation.id)}
                  className="hover:bg-sidebar-accent text-foreground flex w-full flex-col items-start gap-0.5 px-5 py-2.5 text-left text-sm"
                >
                  <span className="w-full truncate">
                    {trimmedQuery ? (
                      <HighlightedText
                        text={conversation.name}
                        query={trimmedQuery}
                      />
                    ) : (
                      conversation.name
                    )}
                  </span>
                  {showSnippet && (
                    <span className="text-muted-foreground line-clamp-2 w-full text-xs">
                      <HighlightedText
                        text={conversation.match_snippet as string}
                        query={trimmedQuery}
                      />
                    </span>
                  )}
                </button>
              );
            })}
        </div>
      </div>
    </WrapperModal>
  );
}
