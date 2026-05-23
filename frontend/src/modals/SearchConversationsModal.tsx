import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import { useTranslation } from 'react-i18next';

import SearchIcon from '../assets/search.svg';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Modal } from '../components/ui/modal';
import { searchConversations } from '../preferences/preferenceApi';

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
          <mark key={idx} className="text-primary bg-transparent font-semibold">
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
  const resultRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ConversationListItem[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

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

  useEffect(() => {
    if (isSearching || visibleConversations.length === 0) {
      setActiveIndex(-1);
      return;
    }

    setActiveIndex((currentIndex) => {
      if (currentIndex >= 0 && currentIndex < visibleConversations.length) {
        return currentIndex;
      }

      return 0;
    });
  }, [isSearching, visibleConversations]);

  useEffect(() => {
    if (activeIndex < 0) return;

    resultRefs.current[activeIndex]?.scrollIntoView({
      block: 'nearest',
    });
  }, [activeIndex]);

  const handleSelect = (id: string) => {
    onSelectConversation(id);
    close();
  };

  const handleInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (visibleConversations.length === 0 || isSearching) return;

    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((currentIndex) =>
        currentIndex < visibleConversations.length - 1 ? currentIndex + 1 : 0,
      );
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((currentIndex) =>
        currentIndex > 0 ? currentIndex - 1 : visibleConversations.length - 1,
      );
      return;
    }

    if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault();
      handleSelect(visibleConversations[activeIndex].id);
    }
  };

  const showEmptyState =
    !!query.trim() && !isSearching && visibleConversations.length === 0;

  return (
    <Modal
      open={true}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      hideTitle
      title={t('modals.searchConversations.searchPlaceholder')}
      showCloseButton={false}
      className="w-[92vw] !max-w-xl !p-0"
      contentClassName="max-h-[70vh]"
    >
      <div className="flex flex-col">
        <div className="border-sidebar-border flex items-center gap-2 border-b px-5 py-4">
          <img src={SearchIcon} alt="search" className="h-4 w-4 opacity-60" />
          <Input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder={t('modals.searchConversations.searchPlaceholder')}
            className="h-auto rounded-none border-none px-0 py-0 text-sm shadow-none focus-visible:ring-0"
          />
        </div>

        <div className="max-h-[55vh] overflow-y-auto py-2" role="listbox">
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
            visibleConversations.map((conversation, index) => {
              const trimmedQuery = query.trim();
              const showSnippet =
                !!trimmedQuery &&
                !!conversation.match_snippet &&
                conversation.match_field !== 'name';
              const isActive = index === activeIndex;

              return (
                <Button
                  key={conversation.id}
                  type="button"
                  variant="ghost"
                  ref={(element) => {
                    resultRefs.current[index] = element;
                  }}
                  onClick={() => handleSelect(conversation.id)}
                  onMouseEnter={() => setActiveIndex(index)}
                  role="option"
                  aria-selected={isActive}
                  className={`text-foreground flex h-auto w-full flex-col items-start gap-0.5 rounded-none px-5 py-2.5 text-left ${
                    isActive ? 'bg-sidebar-accent' : 'hover:bg-sidebar-accent'
                  }`}
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
                </Button>
              );
            })}
        </div>
      </div>
    </Modal>
  );
}
