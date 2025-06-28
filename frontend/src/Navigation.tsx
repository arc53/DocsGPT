import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { NavLink, useNavigate } from 'react-router-dom';

import { Agent } from './agents/types';
import conversationService from './api/services/conversationService';
import userService from './api/services/userService';
import Add from './assets/add.svg';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import Discord from './assets/discord.svg';
import Expand from './assets/expand.svg';
import Github from './assets/github.svg';
import Hamburger from './assets/hamburger.svg';
import openNewChat from './assets/openNewChat.svg';
import Pin from './assets/pin.svg';
import Robot from './assets/robot.svg';
import SettingGear from './assets/settingGear.svg';
import Spark from './assets/spark.svg';
import SpinnerDark from './assets/spinner-dark.svg';
import Spinner from './assets/spinner.svg';
import Twitter from './assets/TwitterX.svg';
import UnPin from './assets/unpin.svg';
import Help from './components/Help';
import {
  handleAbort,
  selectQueries,
  setConversation,
  updateConversationId,
} from './conversation/conversationSlice';
import ConversationTile from './conversation/ConversationTile';
import { useDarkTheme, useMediaQuery } from './hooks';
import useDefaultDocument from './hooks/useDefaultDocument';
import useTokenAuth from './hooks/useTokenAuth';
import DeleteConvModal from './modals/DeleteConvModal';
import JWTModal from './modals/JWTModal';
import { ActiveState } from './models/misc';
import { getConversations } from './preferences/preferenceApi';
import {
  selectAgents,
  selectConversationId,
  selectConversations,
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
import Upload from './upload/Upload';

interface NavigationProps {
  navOpen: boolean;
  setNavOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navigation({ navOpen, setNavOpen }: NavigationProps) {
  const dispatch = useDispatch();
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

  const { isMobile, isTablet } = useMediaQuery();
  const [isDarkTheme] = useDarkTheme();
  const { showTokenModal, handleTokenSubmit } = useTokenAuth();

  const [isDeletingConversation, setIsDeletingConversation] = useState(false);
  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');
  const [recentAgents, setRecentAgents] = useState<Agent[]>([]);

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
    if (!conversations?.data) fetchConversations();
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
    navigate('/');
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

      const response = await conversationService.getConversation(index, token);
      if (!response.ok) {
        navigate('/');
        return;
      }

      const data = await response.json();
      if (!data) return;

      dispatch(setConversation(data.queries));
      dispatch(updateConversationId({ query: { conversationId: index } }));

      if (!data.agent_id) {
        navigate('/');
        return;
      }

      let agent: Agent;
      if (data.is_shared_usage) {
        const sharedResponse = await userService.getSharedAgent(
          data.shared_token,
          token,
        );
        if (!sharedResponse.ok) {
          navigate('/');
          return;
        }
        agent = await sharedResponse.json();
        navigate(`/agents/shared/${agent.shared_token}`);
      } else {
        const agentResponse = await userService.getAgent(data.agent_id, token);
        if (!agentResponse.ok) {
          navigate('/');
          return;
        }
        agent = await agentResponse.json();
        if (agent.shared_token) {
          navigate(`/agents/shared/${agent.shared_token}`);
        } else {
          await Promise.resolve(dispatch(setSelectedAgent(agent)));
          navigate('/');
        }
      }
    } catch (error) {
      console.error('Error handling conversation click:', error);
      navigate('/');
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
          navigate('/');
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

  useDefaultDocument();
  return (
    <>
      {!navOpen && (
        <div className="absolute top-3 left-3 z-20 hidden transition-all duration-25 lg:block">
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setNavOpen(!navOpen);
              }}
            >
              <img
                src={Expand}
                alt="Toggle navigation menu"
                className={`${
                  !navOpen ? 'rotate-180' : 'rotate-0'
                } m-auto transition-all duration-200`}
              />
            </button>
            {queries?.length > 0 && (
              <button
                onClick={() => {
                  newChat();
                }}
              >
                <img
                  src={openNewChat}
                  alt="Start new chat"
                  className="cursor-pointer"
                />
              </button>
            )}
            <div className="text-gray-4000 text-[20px] font-medium">
              DocsGPT
            </div>
          </div>
        </div>
      )}
      <div
        ref={navRef}
        className={`${
          !navOpen && '-ml-96 md:-ml-72'
        } bg-lotion dark:border-r-purple-taupe dark:bg-chinese-black fixed top-0 z-20 flex h-full w-72 flex-col border-r border-b-0 transition-all duration-20 dark:text-white`}
      >
        <div
          className={'visible mt-2 flex h-[6vh] w-full justify-between md:h-12'}
        >
          <div
            className="mx-4 my-auto flex cursor-pointer gap-1.5"
            onClick={() => {
              if (isMobile) {
                setNavOpen(!navOpen);
              }
            }}
          >
            <a href="/" className="flex gap-1.5">
              <img className="mb-2 h-10" src={DocsGPT3} alt="DocsGPT Logo" />
              <p className="my-auto text-2xl font-semibold">DocsGPT</p>
            </a>
          </div>
          <button
            className="float-right mr-5"
            onClick={() => {
              setNavOpen(!navOpen);
            }}
          >
            <img
              src={Expand}
              alt="Toggle navigation menu"
              className={`${
                !navOpen ? 'rotate-180' : 'rotate-0'
              } m-auto transition-all duration-200`}
            />
          </button>
        </div>
        <NavLink
          to={'/'}
          onClick={() => {
            if (isMobile || isTablet) {
              setNavOpen(!navOpen);
            }
            resetConversation();
          }}
          className={({ isActive }) =>
            `${
              isActive ? 'bg-transparent' : ''
            } group border-silver hover:border-rainy-gray dark:border-purple-taupe sticky mx-4 mt-4 flex cursor-pointer gap-2.5 rounded-3xl border p-3 hover:bg-transparent dark:text-white`
          }
        >
          <img
            src={Add}
            alt="Create new chat"
            className="opacity-80 group-hover:opacity-100"
          />
          <p className="text-dove-gray dark:text-chinese-silver dark:group-hover:text-bright-gray text-sm group-hover:text-neutral-600">
            {t('newChat')}
          </p>
        </NavLink>
        <div
          id="conversationsMainDiv"
          className="mb-auto h-[78vh] overflow-x-hidden overflow-y-auto dark:text-white"
        >
          {conversations?.loading && !isDeletingConversation && (
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 transform">
              <img
                src={isDarkTheme ? SpinnerDark : Spinner}
                className="animate-spin cursor-pointer bg-transparent"
                alt="Loading conversations"
              />
            </div>
          )}
          {recentAgents?.length > 0 ? (
            <div>
              <div className="mx-4 my-auto mt-2 flex h-6 items-center">
                <p className="mt-1 ml-4 text-sm font-semibold">Agents</p>
              </div>
              <div className="agents-container">
                <div>
                  {recentAgents.map((agent, idx) => (
                    <div
                      key={idx}
                      className={`group hover:bg-bright-gray dark:hover:bg-dark-charcoal mx-4 my-auto mt-4 flex h-9 cursor-pointer items-center justify-between rounded-3xl pl-4 ${
                        agent.id === selectedAgent?.id && !conversationId
                          ? 'bg-bright-gray dark:bg-dark-charcoal'
                          : ''
                      }`}
                      onClick={() => handleAgentClick(agent)}
                    >
                      <div className="flex items-center gap-2">
                        <div className="flex w-6 justify-center">
                          <img
                            src={
                              agent.image && agent.image.trim() !== ''
                                ? agent.image
                                : Robot
                            }
                            alt="agent-logo"
                            className="h-6 w-6 rounded-full object-contain"
                          />
                        </div>
                        <p className="text-eerie-black dark:text-bright-gray overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                          {agent.name}
                        </p>
                      </div>
                      <div
                        className={`${isMobile || isTablet ? 'flex' : 'invisible flex group-hover:visible'} items-center px-3`}
                      >
                        <button
                          className="rounded-full hover:opacity-75"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleTogglePin(agent);
                          }}
                        >
                          <img
                            src={agent.pinned ? UnPin : Pin}
                            className="h-4 w-4"
                          ></img>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                <div
                  className="hover:bg-bright-gray dark:hover:bg-dark-charcoal mx-4 my-auto mt-2 flex h-9 cursor-pointer items-center gap-2 rounded-3xl pl-4"
                  onClick={() => {
                    dispatch(setSelectedAgent(null));
                    if (isMobile || isTablet) {
                      setNavOpen(false);
                    }
                    navigate('/agents');
                  }}
                >
                  <div className="flex w-6 justify-center">
                    <img
                      src={Spark}
                      alt="manage-agents"
                      className="h-[18px] w-[18px]"
                    />
                  </div>
                  <p className="text-eerie-black dark:text-bright-gray overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                    {t('manageAgents')}
                  </p>
                </div>
              </div>
            </div>
          ) : (
            <div
              className="hover:bg-bright-gray dark:hover:bg-dark-charcoal mx-4 my-auto mt-2 flex h-9 cursor-pointer items-center gap-2 rounded-3xl pl-4"
              onClick={() => {
                if (isMobile || isTablet) {
                  setNavOpen(false);
                }
                dispatch(setSelectedAgent(null));
                navigate('/agents');
              }}
            >
              <div className="flex w-6 justify-center">
                <img
                  src={Spark}
                  alt="manage-agents"
                  className="h-[18px] w-[18px]"
                />
              </div>
              <p className="text-eerie-black dark:text-bright-gray overflow-hidden text-sm leading-6 text-ellipsis whitespace-nowrap">
                {t('manageAgents')}
              </p>
            </div>
          )}
          {conversations?.data && conversations.data.length > 0 ? (
            <div className="mt-7">
              <div className="mx-4 my-auto mt-2 flex h-6 items-center justify-between gap-4 rounded-3xl">
                <p className="mt-1 ml-4 text-sm font-semibold">{t('chats')}</p>
              </div>
              <div className="conversations-container">
                {conversations.data?.map((conversation) => (
                  <ConversationTile
                    key={conversation.id}
                    conversation={conversation}
                    selectConversation={(id) => handleConversationClick(id)}
                    onConversationClick={() => {
                      if (isMobile) {
                        setNavOpen(false);
                      }
                    }}
                    onDeleteConversation={(id) => handleDeleteConversation(id)}
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
        <div className="text-eerie-black flex h-auto flex-col justify-end dark:text-white">
          <div className="dark:border-b-purple-taupe flex flex-col gap-2 border-b py-2">
            <NavLink
              onClick={() => {
                if (isMobile || isTablet) {
                  setNavOpen(false);
                }
                resetConversation();
              }}
              to="/settings"
              className={({ isActive }) =>
                `mx-4 my-auto flex h-9 cursor-pointer items-center gap-4 rounded-3xl hover:bg-gray-100 dark:hover:bg-[#28292E] ${
                  isActive ? 'bg-gray-3000 dark:bg-transparent' : ''
                }`
              }
            >
              <img
                src={SettingGear}
                alt="Settings"
                width={21}
                height={21}
                className="my-auto ml-2 filter dark:invert"
              />
              <p className="text-eerie-black text-sm dark:text-white">
                {t('settings.label')}
              </p>
            </NavLink>
          </div>
          <div className="text-eerie-black flex flex-col justify-end dark:text-white">
            <div className="flex items-center justify-between py-1">
              <Help />

              <div className="flex items-center gap-1 pr-4">
                <NavLink
                  target="_blank"
                  to={'https://discord.gg/WHJdfbQDR4'}
                  className={
                    'rounded-full hover:bg-gray-100 dark:hover:bg-[#28292E]'
                  }
                >
                  <img
                    src={Discord}
                    alt="Join Discord community"
                    className="m-2 w-6 self-center filter dark:invert"
                  />
                </NavLink>
                <NavLink
                  target="_blank"
                  to={'https://twitter.com/docsgptai'}
                  className={
                    'rounded-full hover:bg-gray-100 dark:hover:bg-[#28292E]'
                  }
                >
                  <img
                    src={Twitter}
                    alt="Follow us on Twitter"
                    className="m-2 w-5 self-center filter dark:invert"
                  />
                </NavLink>
                <NavLink
                  target="_blank"
                  to={'https://github.com/arc53/docsgpt'}
                  className={
                    'rounded-full hover:bg-gray-100 dark:hover:bg-[#28292E]'
                  }
                >
                  <img
                    src={Github}
                    alt="View on GitHub"
                    className="m-2 w-6 self-center filter dark:invert"
                  />
                </NavLink>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="dark:border-b-purple-taupe dark:bg-chinese-black sticky z-10 h-16 w-full border-b-2 bg-gray-50 lg:hidden">
        <div className="ml-6 flex h-full items-center gap-6">
          <button
            className="h-6 w-6 lg:hidden"
            onClick={() => setNavOpen(true)}
          >
            <img
              src={Hamburger}
              alt="Toggle mobile menu"
              className="w-7 filter dark:invert"
            />
          </button>
          <div className="text-gray-4000 text-[20px] font-medium">DocsGPT</div>
        </div>
      </div>
      <DeleteConvModal
        modalState={modalStateDeleteConv}
        setModalState={setModalStateDeleteConv}
        handleDeleteAllConv={handleDeleteAllConversations}
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
    </>
  );
}
