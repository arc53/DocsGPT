import React from 'react';
import styled from 'styled-components';
import { useMessages } from '../locale/context';
import type { Messages } from '../locale/index';
import {
  groupConversations,
  relativeDate,
  type HistoryGroup,
  type StoredConversation,
} from '../utils/conversationStore';
import { ArrowLeft, Trash2 } from './icons';
import { IconButton } from './IconButton';
import { focusRing, radii } from './tokens';

const GROUP_LABELS: Record<HistoryGroup, keyof Messages> = {
  today: 'historyToday',
  yesterday: 'historyYesterday',
  previous7Days: 'historyPrevious7Days',
  older: 'historyOlder',
};

const Panel = styled.div`
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  box-sizing: border-box;
`;

const Toolbar = styled.div`
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  box-sizing: border-box;
  padding: 8px 12px 4px 8px;
`;

const Heading = styled.h4`
  flex: 1;
  min-width: 0;
  margin: 0;
  padding: 0 4px;
  overflow: hidden;
  color: ${(props) => props.theme.foreground};
  font-size: 14px;
  font-weight: 600;
  line-height: 1.43;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

// ghost sm: the toolbar's one text button.
const TextButton = styled.button<{ $tone?: 'destructive' | 'primary' }>`
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-sizing: border-box;
  height: 32px;
  margin: 0;
  padding: 0 10px;
  border: none;
  border-radius: ${radii.md};
  background-color: ${(props) =>
    props.$tone === 'destructive' ? props.theme.destructive : 'transparent'};
  color: ${(props) =>
    props.$tone === 'destructive'
      ? props.theme.destructiveForeground
      : props.theme.mutedForeground};
  font-family: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 1;
  white-space: nowrap;
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    color 0.15s ease,
    opacity 0.15s ease;

  &:hover {
    ${(props) =>
      props.$tone === 'destructive'
        ? 'opacity: 0.9;'
        : `background-color: ${props.theme.accent}; color: ${props.theme.foreground};`}
  }

  ${focusRing}
`;

// Alert variant="destructive", with its two answers.
const ConfirmRow = styled.div`
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  box-sizing: border-box;
  margin: 4px 12px 8px 12px;
  padding: 10px 10px 10px 14px;
  border: 1px solid ${(props) => props.theme.destructiveBorder};
  border-radius: ${radii.xl};
  background-color: ${(props) => props.theme.destructiveSoft};
`;

const ConfirmText = styled.p`
  flex: 1 1 140px;
  min-width: 0;
  margin: 0;
  color: ${(props) => props.theme.foreground};
  font-size: 13px;
  line-height: 1.43;
`;

const ConfirmActions = styled.div`
  display: flex;
  gap: 4px;
  margin-left: auto;
`;

const Scroll = styled.div`
  flex: 1;
  min-height: 0;
  box-sizing: border-box;
  padding: 4px 8px 16px 8px;
  overflow-y: auto;
  /* Scrolling past either end doesn't carry on into the host page. */
  overscroll-behavior: contain;
  display: flex;
  flex-direction: column;
  gap: 16px;
  scrollbar-width: thin;
  scrollbar-color: ${(props) => props.theme.scrollbarThumb} transparent;
  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background-color: ${(props) => props.theme.scrollbarThumb};
    border-radius: ${radii.full};
  }
  &::-webkit-scrollbar-track {
    background: transparent;
  }
`;

const Group = styled.section`
  display: flex;
  flex-direction: column;
  gap: 2px;
`;

// The suggested questions' label, on the rows' text edge.
const GroupLabel = styled.h5`
  margin: 0 0 4px 0;
  padding: 0 12px;
  color: ${(props) => props.theme.mutedForeground};
  font-size: 12px;
  font-weight: 500;
  line-height: 1.33;
`;

const List = styled.ul`
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0;
  padding: 0;
  list-style: none;
`;

const DeleteButton = styled(IconButton)`
  width: 28px;
  height: 28px;
  margin-right: 6px;
  opacity: 0;

  &:hover {
    background-color: ${(props) => props.theme.destructiveSoft};
    color: ${(props) => props.theme.destructive};
  }

  &:focus-visible {
    opacity: 1;
  }

  /* No hover to reveal it on touch screens. */
  @media (hover: none) {
    opacity: 1;
  }
`;

// The source rows: rounded-xl, accent on hover and for the open conversation.
const Row = styled.li`
  display: flex;
  align-items: center;
  min-width: 0;
  border-radius: ${radii.xl};
  transition: background-color 0.15s ease;

  &:hover,
  &[data-current='true'] {
    background-color: ${(props) => props.theme.accent};
  }

  &:hover ${DeleteButton}, &:focus-within ${DeleteButton} {
    opacity: 1;
  }
`;

const RowButton = styled.button`
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
  box-sizing: border-box;
  margin: 0;
  padding: 8px 12px;
  border: none;
  border-radius: ${radii.xl};
  background: transparent;
  color: ${(props) => props.theme.foreground};
  font-family: inherit;
  text-align: left;
  cursor: pointer;

  ${focusRing}
`;

const RowTitle = styled.span`
  overflow: hidden;
  font-size: 14px;
  /* Marks the open conversation without the pointer's help. */
  [aria-current='true'] > & {
    font-weight: 500;
  }
  line-height: 1.43;
  white-space: nowrap;
  text-overflow: ellipsis;
`;

const RowDate = styled.span`
  color: ${(props) => props.theme.mutedForeground};
  font-size: 12px;
  line-height: 1.33;
`;

const Empty = styled.p`
  margin: auto 0;
  padding: 24px;
  color: ${(props) => props.theme.mutedForeground};
  font-size: 14px;
  line-height: 1.43;
  text-align: center;
`;

/**
 * The saved conversations, grouped by day, in place of the messages. The
 * arrow keys move between rows.
 */
export const HistoryView = ({
  conversations,
  activeId,
  onSelect,
  onDelete,
  onClearAll,
  onBack,
}: {
  conversations: StoredConversation[];
  activeId: string | null;
  onSelect: (conversation: StoredConversation) => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
  onBack: () => void;
}) => {
  const { locale, t } = useMessages();
  const headingId = React.useId();
  const [confirming, setConfirming] = React.useState(false);
  const backRef = React.useRef<HTMLButtonElement | null>(null);
  const clearRef = React.useRef<HTMLButtonElement | null>(null);
  const cancelRef = React.useRef<HTMLButtonElement | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  // The row index to focus once a deletion has re-rendered the list.
  const focusAfterDeleteRef = React.useRef<number | null>(null);

  const now = Date.now();
  const groups = groupConversations(conversations, now);

  const rowButtons = () =>
    Array.from(
      scrollRef.current?.querySelectorAll<HTMLButtonElement>(
        '[data-history-row]',
      ) ?? [],
    );

  React.useEffect(() => {
    backRef.current?.focus();
  }, []);

  React.useEffect(() => {
    if (confirming) cancelRef.current?.focus();
  }, [confirming]);

  // Nothing left to clear (another tab may have done it).
  React.useEffect(() => {
    if (conversations.length === 0) setConfirming(false);
  }, [conversations.length]);

  React.useLayoutEffect(() => {
    const index = focusAfterDeleteRef.current;
    if (index === null) return;
    focusAfterDeleteRef.current = null;
    const rows = rowButtons();
    (rows[Math.min(index, rows.length - 1)] ?? backRef.current)?.focus();
  }, [conversations]);

  const cancelConfirm = () => {
    setConfirming(false);
    window.requestAnimationFrame(() => clearRef.current?.focus());
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    // Escape first cancels "Clear all"; the panel handles it otherwise.
    if (event.key === 'Escape' && confirming) {
      event.preventDefault();
      event.stopPropagation();
      cancelConfirm();
      return;
    }
    const target = event.target as HTMLElement;
    if (!target.hasAttribute('data-history-row')) return;
    const rows = rowButtons();
    const index = rows.indexOf(target as HTMLButtonElement);
    const next =
      event.key === 'ArrowDown'
        ? index + 1
        : event.key === 'ArrowUp'
          ? index - 1
          : event.key === 'Home'
            ? 0
            : event.key === 'End'
              ? rows.length - 1
              : null;
    if (next === null || next < 0 || next >= rows.length) return;
    event.preventDefault();
    rows[next].focus();
  };

  const deleteRow = (id: string, button: HTMLElement) => {
    const row = button
      .closest('li')
      ?.querySelector<HTMLButtonElement>('[data-history-row]');
    // Focus would fall to the body; keep it on the row taking this one's place.
    if (row) focusAfterDeleteRef.current = rowButtons().indexOf(row);
    onDelete(id);
  };

  return (
    <Panel role="region" aria-labelledby={headingId} onKeyDown={handleKeyDown}>
      <Toolbar>
        <IconButton
          ref={backRef}
          type="button"
          onClick={onBack}
          aria-label={t('backToChat')}
          title={t('backToChat')}
        >
          <ArrowLeft size={16} />
        </IconButton>
        <Heading id={headingId}>{t('historyHeading')}</Heading>
        {conversations.length > 0 && !confirming && (
          <TextButton
            ref={clearRef}
            type="button"
            onClick={() => setConfirming(true)}
          >
            {t('clearAll')}
          </TextButton>
        )}
      </Toolbar>
      {confirming && (
        <ConfirmRow role="group" aria-label={t('clearAllConfirm')}>
          <ConfirmText>{t('clearAllConfirm')}</ConfirmText>
          <ConfirmActions>
            <TextButton ref={cancelRef} type="button" onClick={cancelConfirm}>
              {t('cancel')}
            </TextButton>
            <TextButton
              type="button"
              $tone="destructive"
              onClick={() => {
                setConfirming(false);
                onClearAll();
                window.requestAnimationFrame(() => backRef.current?.focus());
              }}
            >
              {t('clearAllConfirmButton')}
            </TextButton>
          </ConfirmActions>
        </ConfirmRow>
      )}
      <Scroll ref={scrollRef}>
        {groups.length === 0 ? (
          <Empty>{t('historyEmpty')}</Empty>
        ) : (
          groups.map(({ group, items }) => {
            const labelId = `${headingId}-${group}`;
            return (
              <Group key={group} aria-labelledby={labelId}>
                <GroupLabel id={labelId}>{t(GROUP_LABELS[group])}</GroupLabel>
                <List>
                  {items.map((conversation) => {
                    const titleId = `${headingId}-${conversation.id}`;
                    const current = conversation.id === activeId;
                    return (
                      <Row key={conversation.id} data-current={current}>
                        <RowButton
                          type="button"
                          data-history-row=""
                          aria-current={current ? 'true' : undefined}
                          onClick={() => onSelect(conversation)}
                        >
                          <RowTitle id={titleId}>{conversation.title}</RowTitle>
                          <RowDate>
                            {relativeDate(conversation.updatedAt, now, locale)}
                          </RowDate>
                        </RowButton>
                        <DeleteButton
                          type="button"
                          aria-label={t('deleteConversation')}
                          aria-describedby={titleId}
                          title={t('deleteConversation')}
                          onClick={(event) =>
                            deleteRow(conversation.id, event.currentTarget)
                          }
                        >
                          <Trash2 size={16} />
                        </DeleteButton>
                      </Row>
                    );
                  })}
                </List>
              </Group>
            );
          })
        )}
      </Scroll>
    </Panel>
  );
};
