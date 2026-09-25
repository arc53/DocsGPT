import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import {
  LayoutGrid,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Pin,
  PinOff,
  Plus,
  Search as SearchIcon,
  Settings as SettingsIcon,
} from 'lucide-react';

import {
  AGENTS_MANAGE_ROOT,
  agentChatPath,
  sharedAgentPath,
} from './agents/paths';
import { Agent } from './agents/types';
import conversationService from './api/services/conversationService';
import userService from './api/services/userService';
import Discord from './assets/discord.svg';
import Github from './assets/git_nav.svg';
import { Avatar } from './components/ui/avatar';
import { Button } from './components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import Twitter from './assets/TwitterX.svg';
import Help from './components/Help';
import {
  handleAbort,
  loadConversation,
  selectQueries,
  setConversation,
  updateConversationId,
} from './conversation/conversationSlice';
import ConversationTile from './conversation/ConversationTile';
import { useMediaQuery } from './hooks';
import useTokenAuth from './hooks/useTokenAuth';
import { cn } from './lib/utils';
import ConfirmationModal from './modals/ConfirmationModal';
import JWTModal from './modals/JWTModal';
import SearchConversationsModal from './modals/SearchConversationsModal';
import { ActiveState } from './models/misc';
import { getConversations } from './preferences/preferenceApi';
import SectionNav from './navigation/SectionNav';
import SectionRail from './navigation/SectionRail';
import SidebarLevel from './navigation/SidebarLevel';
import {
  getActiveItem,
  getSectionForPath,
  type Section,
} from './navigation/sections';
import { useSidebarLevel } from './navigation/SidebarLevelProvider';
import { useSectionContext } from './navigation/useSectionContext';
import { useLastAppPath } from './navigation/useLastAppPath';
import {
  selectAgents,
  selectConversationId,
  selectConversations,
  selectIsAdmin,
  selectModalStateDeleteConv,
  selectSelectedAgent,
  selectSharedAgents,
  selectToken,
  setAgents,
  setConversations,
  setModalStateDeleteConv,
  setSelectedAgent,
  setSharedAgents,
} from './preferences/preferenceSlice';
import { AppDispatch } from './store';
import TeamSwitcher from './teams/TeamSwitcher';
import Upload from './upload/Upload';

interface NavigationProps {
  navOpen: boolean;
  setNavOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navigation({ navOpen, setNavOpen }: NavigationProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const { t } = useTranslation();

  const token = useSelector(selectToken);
  const queries = useSelector(selectQueries);
  const conversations = useSelector(selectConversations);
  const conversationId = useSelector(selectConversationId);
  const modalStateDeleteConv = useSelector(selectModalStateDeleteConv);
  const agents = useSelector(selectAgents);
  const sharedAgents = useSelector(selectSharedAgents);
  const selectedAgent = useSelector(selectSelectedAgent);
  const isAdmin = useSelector(selectIsAdmin);

  const { isMobile, isTablet } = useMediaQuery();
  const { showTokenModal, handleTokenSubmit } = useTokenAuth();

  // Section state is derived from the route, so deep links and the browser
  // back button keep working without a second source of truth.
  const { section: routeSection, item: routeSectionItem } = useSectionContext();
  const { pending, goToLevel } = useSidebarLevel();

  // While a level change is in flight the sidebar runs ahead of the route,
  // so it can start moving on the click rather than on the commit.
  const activeSection = pending ? pending.section : routeSection;
  const activeSectionItem =
    pending && pending.section
      ? getActiveItem(pending.section, pending.pathname)
      : pending
        ? null
        : routeSectionItem;
  const lastAppPath = useLastAppPath();
  const inSection = Boolean(activeSection);

  // The sidebar is a stack: chats, a section, and a record inside it. A
  // section that declares a parent sits on the third level, above its
  // parent's nav.
  const nestedSection = activeSection?.parentPath ? activeSection : null;
  const topSection = nestedSection
    ? getSectionForPath(nestedSection.parentPath ?? '')
    : activeSection;
  const sidebarDepth = nestedSection ? 2 : activeSection ? 1 : 0;

  // Panels stay mounted after being left so they have something to animate
  // out, and so the one behind is already there to be revealed on the way
  // back. They park off screen, so the cost is a subtree nobody can see.
  const lastTopSection = useRef<Section | null>(null);
  const lastNestedSection = useRef<Section | null>(null);
  if (topSection) lastTopSection.current = topSection;
  if (nestedSection) lastNestedSection.current = nestedSection;
  const topPanel = topSection ?? lastTopSection.current;
  const nestedPanel = nestedSection ?? lastNestedSection.current;

  // Back means "up one level": out of an agent lands on the agent list, out
  // of a top-level section lands back in the app.
  const backLabelFor = (section: Section) =>
    section.parentLabelKey
      ? t(section.parentLabelKey)
      : t('navigation.backToApp');

  const exitSectionFrom = (section: Section | null) => () => {
    if (isMobile || isTablet) setNavOpen(false);
    goToLevel(section?.parentPath ?? lastAppPath.current ?? '/');
  };

  const exitSection = exitSectionFrom(activeSection);
  const backLabel = activeSection
    ? backLabelFor(activeSection)
    : t('navigation.backToApp');

  const closeNavOnMobile = () => {
    if (isMobile || isTablet) setNavOpen(false);
  };

  const [isDeletingConversation, setIsDeletingConversation] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [recentAgents, setRecentAgents] = useState<Agent[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);

  const navRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        navRef.current &&
        !navRef.current.contains(event.target as Node) &&
        (isMobile || isTablet) &&
        navOpen
      ) {
        setNavOpen(false);
      }
    }

    //event listener only for mobile/tablet when nav is open
    if ((isMobile || isTablet) && navOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [navOpen, isMobile, isTablet, setNavOpen]);

  useEffect(() => {
    function handleSearchShortcut(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setSearchOpen(true);
      }
    }

    document.addEventListener('keydown', handleSearchShortcut);
    return () => document.removeEventListener('keydown', handleSearchShortcut);
  }, []);

  async function fetchRecentAgents() {
    try {
      const response = await userService.getPinnedAgents(token);
      if (!response.ok) throw new Error('Failed to fetch pinned agents');
      const pinnedAgents: Agent[] = await response.json();
      if (pinnedAgents.length >= 3) {
        setRecentAgents(pinnedAgents);
        return;
      }
      let tempAgents: Agent[] = [];
      if (!agents) {
        const response = await userService.getAgents(token);
        if (!response.ok) throw new Error('Failed to fetch agents');
        const data: Agent[] = await response.json();
        dispatch(setAgents(data));
        tempAgents = data;
      } else tempAgents = agents;
      const additionalAgents = tempAgents
        .filter(
          (agent: Agent) =>
            agent.status === 'published' &&
            !pinnedAgents.some((pinned) => pinned.id === agent.id),
        )
        .sort(
          (a: Agent, b: Agent) =>
            new Date(b.last_used_at ?? 0).getTime() -
            new Date(a.last_used_at ?? 0).getTime(),
        )
        .slice(0, 3 - pinnedAgents.length);
      setRecentAgents([...pinnedAgents, ...additionalAgents]);
    } catch (error) {
      console.error('Failed to fetch recent agents: ', error);
    }
  }

  async function fetchConversations() {
    dispatch(setConversations({ ...conversations, loading: true }));
    return await getConversations(token)
      .then((fetchedConversations) => {
        dispatch(setConversations(fetchedConversations));
      })
      .catch((error) => {
        console.error('Failed to fetch conversations: ', error);
        dispatch(setConversations({ data: null, loading: false }));
      });
  }

  useEffect(() => {
    fetchRecentAgents();
  }, [agents, sharedAgents, token, dispatch]);

  useEffect(() => {
    if (queries.length === 0) resetConversation();
  }, [conversations?.data, dispatch]);

  const handleDeleteAllConversations = () => {
    setIsDeletingConversation(true);
    conversationService
      .deleteAll(token)
      .then(() => {
        fetchConversations();
      })
      .catch((error) => console.error(error));
  };

  const handleDeleteConversation = (id: string) => {
    setIsDeletingConversation(true);
    conversationService
      .delete(id, {}, token)
      .then(() => {
        fetchConversations();
        resetConversation();
      })
      .catch((error) => console.error(error));
  };

  const handleAgentClick = (agent: Agent) => {
    resetConversation();
    dispatch(setSelectedAgent(agent));
    if (isMobile || isTablet) setNavOpen(!navOpen);
    navigate(agent.id ? agentChatPath(agent.id) : '/c/new');
  };

  const handleTogglePin = (agent: Agent) => {
    userService.togglePinAgent(agent.id ?? '', token).then((response) => {
      if (response.ok) {
        const updatePinnedStatus = (a: Agent) =>
          a.id === agent.id ? { ...a, pinned: !a.pinned } : a;
        dispatch(setAgents(agents?.map(updatePinnedStatus)));
        dispatch(setSharedAgents(sharedAgents?.map(updatePinnedStatus)));
      }
    });
  };

  const handleConversationClick = async (index: string) => {
    try {
      dispatch(setSelectedAgent(null));

      // Pre-fetch to choose the route shape (owned-agent / shared / none).
      const result = await dispatch(
        loadConversation({ id: index, force: true }),
      ).unwrap();
      // Stale: a newer load has already updated Redux; the URL is
      // wherever that newer flow lands, leave it alone.
      if (result.stale) return;
      const data = result.data;
      if (!data) {
        navigate('/c/new');
        return;
      }

      if (!data.agent_id) {
        navigate(`/c/${index}`);
        return;
      }

      let agent: Agent;
      if (data.is_shared_usage) {
        const sharedResponse = await userService.getSharedAgent(
          data.shared_token,
          token,
        );
        if (!sharedResponse.ok) {
          navigate(`/c/${index}`);
          return;
        }
        agent = await sharedResponse.json();
        navigate(sharedAgentPath(agent.shared_token));
      } else {
        const agentResponse = await userService.getAgent(data.agent_id, token);
        if (!agentResponse.ok) {
          navigate(`/c/${index}`);
          return;
        }
        agent = await agentResponse.json();
        if (agent.shared_token) {
          navigate(sharedAgentPath(agent.shared_token));
        } else {
          await Promise.resolve(dispatch(setSelectedAgent(agent)));
          navigate(agentChatPath(data.agent_id, index));
        }
      }
    } catch (error) {
      console.error('Error handling conversation click:', error);
      navigate('/c/new');
    }
  };

  const resetConversation = () => {
    handleAbort();
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
    dispatch(setSelectedAgent(null));
  };

  const newChat = () => {
    if (queries && queries?.length > 0) {
      resetConversation();
    }
    navigate('/c/new');
  };

  async function updateConversationName(updatedConversation: {
    name: string;
    id: string;
  }) {
    await conversationService
      .update(updatedConversation, token)
      .then((response) => response.json())
      .then((data) => {
        if (data) {
          fetchConversations();
        }
      })
      .catch((err) => {
        console.error(err);
      });
  }

  useEffect(() => {
    setNavOpen(!(isMobile || isTablet));
  }, [isMobile, isTablet]);

  return (
    <>
      {(isMobile || isTablet) && navOpen && (
        <div
          className="fixed inset-0 z-10 bg-black opacity-50 transition-opacity duration-300"
          onClick={() => setNavOpen(false)}
        />
      )}

      {/* Icon rail (desktop only, when sidebar collapsed) */}
      {!navOpen && !isMobile && !isTablet && (
        <div
          ref={navRef}
          className="bg-sidebar border-border scrollbar-overlay fixed top-0 left-0 z-10 hidden h-full w-14 flex-col items-center gap-2 overflow-x-hidden overflow-y-auto border-r py-3 lg:flex"
        >
          <Button
            type="button"
            variant="ghost-muted"
            size="icon"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation menu"
          >
            <PanelLeftOpen className="size-5" />
          </Button>
          {activeSection ? (
            <SectionRail
              section={activeSection}
              activeItemKey={activeSectionItem?.key}
              isAdmin={isAdmin}
              onBack={exitSection}
              backLabel={backLabel}
            />
          ) : (
            <>
              {queries?.length > 0 && (
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="icon"
                  onClick={() => newChat()}
                  aria-label="Start new chat"
                >
                  <Plus className="size-5" />
                </Button>
              )}
              <Button
                type="button"
                variant="ghost-muted"
                size="icon"
                onClick={() => {
                  dispatch(setSelectedAgent(null));
                  goToLevel(AGENTS_MANAGE_ROOT);
                }}
                aria-label={t('manageAgents')}
              >
                <LayoutGrid className="size-5" />
              </Button>
              {conversations?.data && conversations.data.length > 0 && (
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="icon"
                  onClick={() => setSearchOpen(true)}
                  aria-label={t('modals.searchConversations.searchPlaceholder')}
                  title={t('modals.searchConversations.searchPlaceholder')}
                >
                  <SearchIcon className="size-5" />
                </Button>
              )}
              <div className="mt-auto flex flex-col items-center gap-2">
                <Button
                  type="button"
                  variant="ghost-muted"
                  size="icon"
                  onClick={() => goToLevel('/settings')}
                  aria-label={t('settings.label')}
                >
                  <SettingsIcon className="size-5" />
                </Button>
              </div>
            </>
          )}
        </div>
      )}
      <div
        className={cn(
          'bg-sidebar dark:border-r-sidebar-border fixed top-0 z-20 flex h-full w-72 flex-col border-r border-b-0 transition-all duration-300 ease-in-out dark:text-white',
          !navOpen && '-ml-96 md:-ml-72',
        )}
      >
        <div
          className={
            'visible mt-2 flex h-[6vh] w-full items-center justify-between gap-1 px-2 md:h-12'
          }
        >
          <div className="min-w-0 flex-1">
            <TeamSwitcher
              onNavigate={() => {
                if (isMobile || isTablet) {
                  setNavOpen(false);
                }
              }}
            />
          </div>
          <Button
            type="button"
            variant="ghost-muted"
            size="icon"
            className="shrink-0"
            onClick={() => {
              setNavOpen(!navOpen);
            }}
            aria-label={navOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          >
            {navOpen ? (
              <PanelLeftClose className="size-5 transition-all duration-300 ease-in-out hover:scale-110" />
            ) : (
              <PanelLeftOpen className="size-5 transition-all duration-300 ease-in-out hover:scale-110" />
            )}
          </Button>
        </div>
        {/* The chat list and the section nav swap places here. Both stay
            mounted so the conversation list keeps its scroll position while
            the user is away in a section. */}
        <div className="relative flex min-h-0 flex-1 overflow-hidden">
          <SidebarLevel depth={0} current={sidebarDepth}>
            <NavLink
              to={'/c/new'}
              onClick={() => {
                if (isMobile || isTablet) {
                  setNavOpen(!navOpen);
                }
                resetConversation();
              }}
              className={({ isActive }) =>
                `${
                  isActive ? 'bg-transparent' : ''
                } group border-sidebar-border hover:border-sidebar-border sticky mx-4 mt-4 flex cursor-pointer items-center gap-2.5 rounded-3xl border p-3 hover:bg-transparent dark:text-white`
              }
            >
              <Plus
                className="text-muted-foreground group-hover:text-foreground size-5 shrink-0"
                aria-label="Create new chat"
              />
              <p className="text-muted-foreground group-hover:text-foreground text-sm">
                {t('newChat')}
              </p>
            </NavLink>
            <div
              id="conversationsMainDiv"
              className="scrollbar-overlay min-h-0 flex-1 overflow-x-hidden overflow-y-auto dark:text-white"
            >
              {conversations?.loading && !isDeletingConversation && (
                <div
                  className="text-foreground absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 transform dark:text-white"
                  role="status"
                  aria-label="Loading conversations"
                >
                  <Spinner size="sm" />
                </div>
              )}
              {recentAgents?.length > 0 ? (
                <div>
                  <div className="mx-4 my-auto mt-2 flex h-6 items-center">
                    <p className="mt-1 ml-4 text-sm font-semibold">
                      {t('navigation.agents')}
                    </p>
                  </div>
                  <div>
                    <div>
                      {recentAgents.map((agent, idx) => (
                        <div
                          key={idx}
                          className={`group hover:bg-sidebar-accent mx-4 my-auto mt-4 flex h-9 cursor-pointer items-center justify-between rounded-3xl pl-3 ${
                            agent.id === selectedAgent?.id && !conversationId
                              ? 'bg-sidebar-accent'
                              : ''
                          }`}
                          onClick={() => handleAgentClick(agent)}
                        >
                          <div className="flex items-center gap-2.5">
                            <div className="flex w-6 justify-center">
                              <Avatar
                                src={agent.image}
                                alt="agent-logo"
                                shape="circle"
                                className="overflow-hidden"
                                imgClassName="h-6 w-6 object-contain"
                              />
                            </div>
                            <p className="text-foreground overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                              {agent.name}
                            </p>
                          </div>
                          <div
                            className={`${isMobile || isTablet ? 'flex' : 'invisible flex group-hover:visible'} items-center px-1.5`}
                          >
                            <Button
                              type="button"
                              variant="ghost-on-accent"
                              size="icon-xs"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleTogglePin(agent);
                              }}
                              aria-label={
                                agent.pinned ? 'Unpin agent' : 'Pin agent'
                              }
                            >
                              {agent.pinned ? <PinOff /> : <Pin />}
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                    <Button
                      variant="sidebar-item"
                      asChild
                      className="mx-4 my-auto mt-2 flex"
                    >
                      <NavLink
                        to={AGENTS_MANAGE_ROOT}
                        end
                        onClick={(event) => {
                          if (event.metaKey || event.ctrlKey || event.shiftKey)
                            return;
                          event.preventDefault();
                          dispatch(setSelectedAgent(null));
                          closeNavOnMobile();
                          goToLevel(AGENTS_MANAGE_ROOT);
                        }}
                      >
                        <div className="flex w-6 justify-center">
                          <LayoutGrid
                            className="text-muted-foreground size-5"
                            aria-label="manage-agents"
                          />
                        </div>
                        <p className="text-foreground overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                          {t('manageAgents')}
                        </p>
                      </NavLink>
                    </Button>
                  </div>
                </div>
              ) : (
                <Button
                  variant="sidebar-item"
                  asChild
                  className="mx-4 my-auto mt-2 flex"
                >
                  <NavLink
                    to={AGENTS_MANAGE_ROOT}
                    end
                    onClick={(event) => {
                      if (event.metaKey || event.ctrlKey || event.shiftKey)
                        return;
                      event.preventDefault();
                      closeNavOnMobile();
                      dispatch(setSelectedAgent(null));
                      goToLevel(AGENTS_MANAGE_ROOT);
                    }}
                  >
                    <LayoutGrid
                      className="text-muted-foreground size-5 shrink-0"
                      aria-label="manage-agents"
                    />
                    <p className="text-foreground overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                      {t('manageAgents')}
                    </p>
                  </NavLink>
                </Button>
              )}
              {conversations?.data && conversations.data.length > 0 ? (
                <div className="mt-7">
                  <div className="my-auto mt-2 ml-2.75 flex h-9 items-center justify-between gap-4 rounded-3xl p-1">
                    <p className="mt-1 ml-4 text-sm font-semibold">
                      {t('chats')}
                    </p>
                    <Button
                      type="button"
                      variant="ghost-muted"
                      size="icon"
                      shape="pill"
                      onClick={() => setSearchOpen(true)}
                      className="mr-1"
                      aria-label={t(
                        'modals.searchConversations.searchPlaceholder',
                      )}
                      title={t('modals.searchConversations.searchPlaceholder')}
                    >
                      <SearchIcon className="size-5" aria-label="search" />
                    </Button>
                  </div>
                  <div>
                    {(conversations.data ?? []).map((conversation) => (
                      <ConversationTile
                        key={conversation.id}
                        conversation={conversation}
                        selectConversation={(id) => handleConversationClick(id)}
                        onConversationClick={() => {
                          if (isMobile) {
                            setNavOpen(false);
                          }
                        }}
                        onDeleteConversation={(id) =>
                          handleDeleteConversation(id)
                        }
                        onSave={(conversation) =>
                          updateConversationName(conversation)
                        }
                      />
                    ))}
                  </div>
                </div>
              ) : (
                <></>
              )}
            </div>
          </SidebarLevel>
          <SidebarLevel depth={1} current={sidebarDepth}>
            {topPanel && (
              <SectionNav
                section={topPanel}
                activeItemKey={
                  topPanel === activeSection
                    ? activeSectionItem?.key
                    : undefined
                }
                isAdmin={isAdmin}
                onBack={exitSectionFrom(topPanel)}
                backLabel={backLabelFor(topPanel)}
                onNavigate={closeNavOnMobile}
              />
            )}
          </SidebarLevel>
          <SidebarLevel depth={2} current={sidebarDepth}>
            {nestedPanel && (
              <SectionNav
                section={nestedPanel}
                activeItemKey={
                  nestedPanel === activeSection
                    ? activeSectionItem?.key
                    : undefined
                }
                isAdmin={isAdmin}
                onBack={exitSectionFrom(nestedPanel)}
                backLabel={backLabelFor(nestedPanel)}
                onNavigate={closeNavOnMobile}
              />
            )}
          </SidebarLevel>
        </div>
        <div className="text-foreground flex h-auto shrink-0 flex-col justify-end dark:text-white">
          {/* Inside a section its own nav is the way around, so this entry
              would only duplicate what is already on screen. Entering settings
              no longer clears the conversation either, so the section's back
              button can return to it. */}
          <div
            className={cn(
              'dark:border-b-sidebar-border flex flex-col gap-2 border-b py-2',
              inSection && 'hidden',
            )}
          >
            <Button
              variant="sidebar-item"
              asChild
              className="mx-4 my-auto flex"
            >
              <Link
                to="/settings"
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                  event.preventDefault();
                  closeNavOnMobile();
                  goToLevel('/settings');
                }}
              >
                <SettingsIcon
                  className="text-muted-foreground size-5 shrink-0"
                  aria-label="Settings"
                />
                <p className="text-foreground text-sm dark:text-white">
                  {t('settings.label')}
                </p>
              </Link>
            </Button>
          </div>
          <div className="text-foreground flex flex-col justify-end dark:text-white">
            <div className="flex items-center justify-between py-1">
              <Help />

              <div className="flex items-center gap-1 pr-4">
                <NavLink
                  target="_blank"
                  to={'https://discord.gg/vN7YFfdMpj'}
                  className={'hover:bg-sidebar-accent rounded-full'}
                >
                  <img
                    src={Discord}
                    width={24}
                    height={24}
                    alt="Join Discord community"
                    className="m-2 w-6 self-center filter dark:invert"
                  />
                </NavLink>
                <NavLink
                  target="_blank"
                  to={'https://x.com/docsgptai'}
                  className={'hover:bg-sidebar-accent rounded-full'}
                >
                  <img
                    src={Twitter}
                    width={20}
                    height={20}
                    alt="Follow us on X"
                    className="m-2 self-center filter dark:invert"
                  />
                </NavLink>
                <NavLink
                  target="_blank"
                  to={'https://github.com/arc53/docsgpt'}
                  className={'hover:bg-sidebar-accent rounded-full'}
                >
                  <img
                    src={Github}
                    alt="View on GitHub"
                    width={28}
                    height={28}
                    className="m-2 self-center filter dark:invert"
                  />
                </NavLink>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="dark:border-b-sidebar-border bg-sidebar sticky z-10 h-16 w-full border-b-2 lg:hidden">
        <div className="relative flex h-full items-center">
          <Button
            type="button"
            variant="ghost-muted"
            size="icon"
            className="ml-4 size-9 lg:hidden"
            onClick={() => setNavOpen(true)}
            aria-label="Toggle mobile menu"
          >
            <Menu className="size-5" />
          </Button>
        </div>
      </div>
      <ConfirmationModal
        message={t('modals.deleteConv.confirm')}
        modalState={modalStateDeleteConv}
        setModalState={(state) => dispatch(setModalStateDeleteConv(state))}
        submitLabel={t('modals.deleteConv.delete')}
        handleSubmit={handleDeleteAllConversations}
        variant="danger"
      />
      {uploadModalState === 'ACTIVE' && (
        <Upload
          receivedFile={[]}
          setModalState={setUploadModalState}
          isOnboarding={false}
          renderTab={null}
          close={() => setUploadModalState('INACTIVE')}
        ></Upload>
      )}
      <JWTModal
        modalState={showTokenModal ? 'ACTIVE' : 'INACTIVE'}
        handleTokenSubmit={handleTokenSubmit}
      />
      {searchOpen && (
        <SearchConversationsModal
          close={() => setSearchOpen(false)}
          conversations={conversations?.data ?? []}
          token={token}
          onSelectConversation={(id) => {
            handleConversationClick(id);
            if (isMobile || isTablet) setNavOpen(false);
          }}
        />
      )}
    </>
  );
}
