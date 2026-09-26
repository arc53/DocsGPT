import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  Command,
  CommandDialog,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '../components/ui/command';
import { Modal } from '../components/ui/modal';
import { useMediaQuery } from '../hooks';
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

/**
 * Conversation search palette. At `sm`+ it is a `CommandDialog`; on phones it
 * is the `Modal` bottom sheet with the same Command parts inside, showing
 * titles only. Results come from the debounced server search and are shown
 * unfiltered (`shouldFilter={false}`); cmdk owns arrow-key navigation and
 * Enter/click open the highlighted conversation via `onSelect`.
 */
export default function SearchConversationsModal({
  close,
  conversations,
  token,
  onSelectConversation,
}: SearchConversationsModalProps) {
  const { t } = useTranslation();
  const { isMobile } = useMediaQuery();
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<ConversationListItem[] | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedId, setSelectedId] = useState('');

  const title = t('modals.searchConversations.searchPlaceholder');

  // The branch can switch after mount (useMediaQuery settles in an effect),
  // remounting the input, so refocus it whenever the branch changes.
  useEffect(() => {
    inputRef.current?.focus();
  }, [isMobile]);

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

  // Keep the highlighted row when it survives a list change, otherwise
  // highlight the first row, so Enter always has a target.
  useEffect(() => {
    if (isSearching || visibleConversations.length === 0) {
      setSelectedId('');
      return;
    }
    setSelectedId((current) =>
      visibleConversations.some((c) => c.id === current)
        ? current
        : visibleConversations[0].id,
    );
  }, [isSearching, visibleConversations]);

  const handleSelect = (id: string) => {
    onSelectConversation(id);
    close();
  };

  const trimmedQuery = query.trim();
  const showEmptyState =
    !!trimmedQuery && !isSearching && visibleConversations.length === 0;

  const status = (
    <>
      {isSearching && (
        <div className="text-muted-foreground px-3 py-3 text-xs">
          {t('modals.searchConversations.loading')}
        </div>
      )}
      {showEmptyState && (
        <div className="text-muted-foreground px-3 py-3 text-xs">
          {t('modals.searchConversations.noResults')}
        </div>
      )}
    </>
  );

  const renderItems = (withSnippet: boolean) =>
    !isSearching &&
    visibleConversations.map((conversation) => {
      const titleNode = trimmedQuery ? (
        <HighlightedText text={conversation.name} query={trimmedQuery} />
      ) : (
        conversation.name
      );
      const showSnippet =
        withSnippet &&
        !!trimmedQuery &&
        !!conversation.match_snippet &&
        conversation.match_field !== 'name';

      return (
        <CommandItem
          key={conversation.id}
          value={conversation.id}
          onSelect={() => handleSelect(conversation.id)}
        >
          {withSnippet ? (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate">{titleNode}</span>
              {showSnippet && (
                <span className="text-muted-foreground line-clamp-2 text-xs">
                  <HighlightedText
                    text={conversation.match_snippet as string}
                    query={trimmedQuery}
                  />
                </span>
              )}
            </div>
          ) : (
            <span className="truncate">{titleNode}</span>
          )}
        </CommandItem>
      );
    });

  const commandProps = {
    shouldFilter: false,
    label: title,
    value: selectedId,
    onValueChange: setSelectedId,
  };

  const input = (
    <CommandInput
      ref={inputRef}
      value={query}
      onValueChange={setQuery}
      placeholder={title}
    />
  );

  const onOpenChange = (open: boolean) => {
    if (!open) close();
  };

  if (isMobile) {
    return (
      <Modal
        open={true}
        onOpenChange={onOpenChange}
        hideTitle
        title={title}
        showCloseButton={false}
        mobileVariant="sheet"
        contentClassName="-mx-3 -mt-3 flex flex-col"
      >
        <Command variant="palette" {...commandProps} className="min-h-0">
          {input}
          <CommandList className="max-h-none">
            <div className="py-1">
              {status}
              {renderItems(false)}
            </div>
          </CommandList>
        </Command>
      </Modal>
    );
  }

  return (
    <CommandDialog
      open={true}
      onOpenChange={onOpenChange}
      title={title}
      description={title}
      showCloseButton={false}
      commandProps={commandProps}
    >
      {input}
      <CommandList>
        {status}
        {!isSearching && visibleConversations.length > 0 && (
          <CommandGroup>{renderItems(true)}</CommandGroup>
        )}
      </CommandList>
    </CommandDialog>
  );
}
