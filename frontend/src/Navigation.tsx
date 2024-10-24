import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useDispatch, useSelector } from 'react-redux';
import { NavLink, useNavigate } from 'react-router-dom';
import conversationService from './api/services/conversationService';
import userService from './api/services/userService';
import Add from './assets/add.svg';
import openNewChat from './assets/openNewChat.svg';
import Hamburger from './assets/hamburger.svg';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import Discord from './assets/discord.svg';
import Expand from './assets/expand.svg';
import Github from './assets/github.svg';
import SettingGear from './assets/settingGear.svg';
import Twitter from './assets/TwitterX.svg';
import UploadIcon from './assets/upload.svg';
import SourceDropdown from './components/SourceDropdown';
import {
  setConversation,
  updateConversationId,
} from './conversation/conversationSlice';
import ConversationTile from './conversation/ConversationTile';
import { useDarkTheme, useMediaQuery, useOutsideAlerter } from './hooks';
import useDefaultDocument from './hooks/useDefaultDocument';
import DeleteConvModal from './modals/DeleteConvModal';
import { ActiveState, Doc } from './models/misc';
import APIKeyModal from './preferences/APIKeyModal';
import { getConversations, getDocs } from './preferences/preferenceApi';
import {
  selectApiKeyStatus,
  selectConversationId,
  selectConversations,
  selectModalStateDeleteConv,
  selectSelectedDocs,
  selectSelectedDocsStatus,
  selectSourceDocs,
  setConversations,
  setModalStateDeleteConv,
  setSelectedDocs,
  setSourceDocs,
} from './preferences/preferenceSlice';
import Spinner from './assets/spinner.svg';
import SpinnerDark from './assets/spinner-dark.svg';
import { selectQueries } from './conversation/conversationSlice';
import Upload from './upload/Upload';
import Help from './components/Help';

interface NavigationProps {
  navOpen: boolean;
  setNavOpen: React.Dispatch<React.SetStateAction<boolean>>;
}
/* const NavImage: React.FC<{
  Light: string | undefined;
  Dark: string | undefined;
}> = ({ Light, Dark }) => {
  return (
    <>
      <img src={Dark} alt="icon" className="ml-2 hidden w-5 dark:block " />
      <img src={Light} alt="icon" className="ml-2 w-5 dark:hidden filter dark:invert" />
    </>
  );
};
NavImage.propTypes = {
  Light: PropTypes.string,
  Dark: PropTypes.string,
}; */
export default function Navigation({ navOpen, setNavOpen }: NavigationProps) {
  const dispatch = useDispatch();
  const queries = useSelector(selectQueries);
  const docs = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);
  const conversations = useSelector(selectConversations);
  const modalStateDeleteConv = useSelector(selectModalStateDeleteConv);
  const conversationId = useSelector(selectConversationId);
  const [isDeletingConversation, setIsDeletingConversation] = useState(false);

  const { isMobile } = useMediaQuery();
  const [isDarkTheme] = useDarkTheme();
  const [isDocsListOpen, setIsDocsListOpen] = useState(false);
  const { t } = useTranslation();
  const isApiKeySet = useSelector(selectApiKeyStatus);
  const [apiKeyModalState, setApiKeyModalState] =
    useState<ActiveState>('INACTIVE');

  const isSelectedDocsSet = useSelector(selectSelectedDocsStatus);
  const [selectedDocsModalState, setSelectedDocsModalState] =
    useState<ActiveState>(isSelectedDocsSet ? 'INACTIVE' : 'ACTIVE');

  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');

  const navRef = useRef(null);

  const navigate = useNavigate();

  useEffect(() => {
    if (!conversations?.data) {
      fetchConversations();
    }
    if (queries.length === 0) {
      resetConversation();
    }
  }, [conversations?.data, dispatch]);

  async function fetchConversations() {
    dispatch(setConversations({ ...conversations, loading: true }));
    return await getConversations()
      .then((fetchedConversations) => {
        dispatch(setConversations(fetchedConversations));
      })
      .catch((error) => {
        console.error('Failed to fetch conversations: ', error);
        dispatch(setConversations({ data: null, loading: false }));
      });
  }

  const handleDeleteAllConversations = () => {
    setIsDeletingConversation(true);
    conversationService
      .deleteAll()
      .then(() => {
        fetchConversations();
      })
      .catch((error) => console.error(error));
  };

  const handleDeleteConversation = (id: string) => {
    setIsDeletingConversation(true);
    conversationService
      .delete(id, {})
      .then(() => {
        fetchConversations();
        resetConversation();
      })
      .catch((error) => console.error(error));
  };

  const handleDeleteClick = (doc: Doc) => {
    userService
      .deletePath(doc.id ?? '')
      .then(() => {
        return getDocs();
      })
      .then((updatedDocs) => {
        dispatch(setSourceDocs(updatedDocs));
        dispatch(
          setSelectedDocs(
            updatedDocs?.find((doc) => doc.name.toLowerCase() === 'default'),
          ),
        );
      })
      .catch((error) => console.error(error));
  };

  const handleConversationClick = (index: string) => {
    conversationService
      .getConversation(index)
      .then((response) => response.json())
      .then((data) => {
        navigate('/');
        dispatch(setConversation(data));
        dispatch(
          updateConversationId({
            query: { conversationId: index },
          }),
        );
      });
  };

  const resetConversation = () => {
    dispatch(setConversation([]));
    dispatch(
      updateConversationId({
        query: { conversationId: null },
      }),
    );
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
      .update(updatedConversation)
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
  useOutsideAlerter(navRef, () => {
    if (isMobile && navOpen && apiKeyModalState === 'INACTIVE') {
      setNavOpen(false);
      setIsDocsListOpen(false);
    }
  }, [navOpen, isDocsListOpen, apiKeyModalState]);

  /*
    Needed to fix bug where if mobile nav was closed and then window was resized to desktop, nav would still be closed but the button to open would be gone, as per #1 on issue #146
  */

  useEffect(() => {
    setNavOpen(!isMobile);
  }, [isMobile]);
  useDefaultDocument();

  return (
    <>
      {!navOpen && (
        <div className="duration-25 absolute  top-3 left-3 z-20 hidden transition-all md:block">
          <div className="flex gap-3 items-center">
            <button
              onClick={() => {
                setNavOpen(!navOpen);
              }}
            >
              <img
                src={Expand}
                alt="menu toggle"
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
                  alt="open new chat icon"
                  className="cursor-pointer"
                />
              </button>
            )}
            <div className="text-[#949494] font-medium text-[20px]">
              DocsGPT
            </div>
          </div>
        </div>
      )}
      <div
        ref={navRef}
        className={`${
          !navOpen && '-ml-96 md:-ml-[18rem]'
        } duration-20 fixed top-0 z-40 flex h-full w-72 flex-col border-r-[1px] border-b-0 bg-white transition-all dark:border-r-purple-taupe dark:bg-chinese-black dark:text-white`}
      >
        <div
          className={'visible mt-2 flex h-[6vh] w-full justify-between md:h-12'}
        >
          <div
            className="my-auto mx-4 flex cursor-pointer gap-1.5"
            onClick={() => {
              if (isMobile) {
                setNavOpen(!navOpen);
              }
            }}
          >
            <a href="/" className="flex gap-1.5">
              <img className="mb-2 h-10" src={DocsGPT3} alt="" />
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
              alt="menu toggle"
              className={`${
                !navOpen ? 'rotate-180' : 'rotate-0'
              } m-auto transition-all duration-200`}
            />
          </button>
        </div>
        <NavLink
          to={'/'}
          onClick={() => {
            if (isMobile) {
              setNavOpen(!navOpen);
            }
            resetConversation();
          }}
          className={({ isActive }) =>
            `${
              isActive ? 'bg-gray-3000 dark:bg-transparent' : ''
            } group sticky mx-4 mt-4 flex cursor-pointer gap-2.5 rounded-3xl border border-silver p-3 hover:border-rainy-gray hover:bg-gray-3000 dark:border-purple-taupe dark:text-white dark:hover:bg-transparent`
          }
        >
          <img
            src={Add}
            alt="new"
            className="opacity-80 group-hover:opacity-100"
          />
          <p className=" text-sm text-dove-gray group-hover:text-neutral-600 dark:text-chinese-silver dark:group-hover:text-bright-gray">
            {t('newChat')}
          </p>
        </NavLink>
        <div
          id="conversationsMainDiv"
          className="mb-auto h-[78vh] overflow-y-auto overflow-x-hidden dark:text-white"
        >
          {conversations?.loading && !isDeletingConversation && (
            <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2">
              <img
                src={isDarkTheme ? SpinnerDark : Spinner}
                className="animate-spin cursor-pointer bg-transparent"
                alt="Loading..."
              />
            </div>
          )}
          {conversations?.data && conversations.data.length > 0 ? (
            <div>
              <div className=" my-auto mx-4 mt-2 flex h-6 items-center justify-between gap-4 rounded-3xl">
                <p className="mt-1 ml-4 text-sm font-semibold">{t('chats')}</p>
              </div>
              <div className="conversations-container">
                {conversations.data?.map((conversation) => (
                  <ConversationTile
                    key={conversation.id}
                    conversation={conversation}
                    selectConversation={(id) => handleConversationClick(id)}
                    onCoversationClick={() => {
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
        <div className="flex h-auto flex-col justify-end text-eerie-black dark:text-white">
          <div className="flex flex-col-reverse border-b-[1px] dark:border-b-purple-taupe">
            <div className="relative my-4 mx-4 flex gap-2">
              <SourceDropdown
                options={docs}
                selectedDocs={selectedDocs}
                setSelectedDocs={setSelectedDocs}
                isDocsListOpen={isDocsListOpen}
                setIsDocsListOpen={setIsDocsListOpen}
                handleDeleteClick={handleDeleteClick}
                handlePostDocumentSelect={(option?: string) => {
                  if (isMobile) {
                    setNavOpen(!navOpen);
                  }
                }}
              />
              <img
                className="mt-2 h-9 w-9 hover:cursor-pointer"
                src={UploadIcon}
                onClick={() => {
                  setUploadModalState('ACTIVE');
                  if (isMobile) {
                    setNavOpen(!navOpen);
                  }
                }}
              ></img>
            </div>
            <p className="ml-5 mt-3 text-sm font-semibold">{t('sourceDocs')}</p>
          </div>
          <div className="flex flex-col gap-2 border-b-[1px] py-2 dark:border-b-purple-taupe">
            <NavLink
              onClick={() => {
                if (isMobile) {
                  setNavOpen(!navOpen);
                }
                resetConversation();
              }}
              to="/settings"
              className={({ isActive }) =>
                `my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100 dark:hover:bg-[#28292E] ${
                  isActive ? 'bg-gray-3000 dark:bg-transparent' : ''
                }`
              }
            >
              <img
                src={SettingGear}
                alt="icon"
                className="ml-2 w-5 filter dark:invert"
              />
              <p className="my-auto text-sm text-eerie-black  dark:text-white">
                {t('settings.label')}
              </p>
            </NavLink>
          </div>
          <div className="flex flex-col justify-end text-eerie-black dark:text-white">
            <div className="flex justify-between items-center py-1">
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
                    alt="discord"
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
                    alt="x"
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
                    alt="github"
                    className="m-2 w-6 self-center filter dark:invert"
                  />
                </NavLink>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="sticky z-10 h-16 w-full border-b-2 bg-gray-50 dark:border-b-purple-taupe dark:bg-chinese-black md:hidden">
        <div className="flex gap-6 items-center h-full ml-6 ">
          <button
            className=" h-6 w-6 md:hidden"
            onClick={() => setNavOpen(true)}
          >
            <img
              src={Hamburger}
              alt="menu toggle"
              className="w-7 filter dark:invert"
            />
          </button>
          <div className="text-[#949494] font-medium text-[20px]">DocsGPT</div>
        </div>
      </div>
      <APIKeyModal
        modalState={apiKeyModalState}
        setModalState={setApiKeyModalState}
        isCancellable={isApiKeySet}
      />
      <DeleteConvModal
        modalState={modalStateDeleteConv}
        setModalState={setModalStateDeleteConv}
        handleDeleteAllConv={handleDeleteAllConversations}
      />
      <Upload
        modalState={uploadModalState}
        setModalState={setUploadModalState}
        isOnboarding={false}
      ></Upload>
    </>
  );
}
