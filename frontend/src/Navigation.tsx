import { useEffect, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { NavLink, useNavigate } from 'react-router-dom';
import DocsGPT3 from './assets/cute_docsgpt3.svg';
import Documentation from './assets/documentation.svg';
import Discord from './assets/discord.svg';
import Arrow2 from './assets/dropdown-arrow.svg';
import Expand from './assets/expand.svg';
import Exit from './assets/exit.svg';
import Github from './assets/github.svg';
import Hamburger from './assets/hamburger.svg';
import Info from './assets/info.svg';
import SettingGear from './assets/settingGear.svg';
import Documentation from './assets/documentation.svg';
import Discord from './assets/discord.svg';
import Github from './assets/github.svg';
import Key from './assets/key.svg';
import Add from './assets/add.svg';
import UploadIcon from './assets/upload.svg';
import { ActiveState } from './models/misc';
import APIKeyModal from './preferences/APIKeyModal';
import {
  selectApiKeyStatus,
  selectSelectedDocs,
  selectSelectedDocsStatus,
  selectSourceDocs,
  setSelectedDocs,
  selectConversations,
  setConversations,
  selectConversationId,
} from './preferences/preferenceSlice';
import {
  setConversation,
  updateConversationId,
} from './conversation/conversationSlice';
import { useMediaQuery, useOutsideAlerter } from './hooks';
import Upload from './upload/Upload';
import { Doc, getConversations } from './preferences/preferenceApi';
import SelectDocsModal from './preferences/SelectDocsModal';
import ConversationTile from './conversation/ConversationTile';

interface NavigationProps {
  navOpen: boolean;
  setNavOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navigation({ navOpen, setNavOpen }: NavigationProps) {
  const dispatch = useDispatch();
  const docs = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);
  const conversations = useSelector(selectConversations);
  const conversationId = useSelector(selectConversationId);
  const { isMobile } = useMediaQuery();

  const [isDocsListOpen, setIsDocsListOpen] = useState(false);

  const isApiKeySet = useSelector(selectApiKeyStatus);
  const [apiKeyModalState, setApiKeyModalState] =
    useState<ActiveState>('INACTIVE');

  const isSelectedDocsSet = useSelector(selectSelectedDocsStatus);
  const [selectedDocsModalState, setSelectedDocsModalState] =
    useState<ActiveState>(isSelectedDocsSet ? 'INACTIVE' : 'ACTIVE');

  const [uploadModalState, setUploadModalState] =
    useState<ActiveState>('INACTIVE');

  const navRef = useRef(null);
  const apiHost = import.meta.env.VITE_API_HOST || 'https://docsapi.arc53.com';
  const embeddingsName =
    import.meta.env.VITE_EMBEDDINGS_NAME || 'openai_text-embedding-ada-002';

  const navigate = useNavigate();

  useEffect(() => {
    if (!conversations) {
      fetchConversations();
    }
  }, [conversations, dispatch]);

  async function fetchConversations() {
    return await getConversations()
      .then((fetchedConversations) => {
        dispatch(setConversations(fetchedConversations));
      })
      .catch((error) => {
        console.error('Failed to fetch conversations: ', error);
      });
  }

  const handleDeleteConversation = (id: string) => {
    fetch(`${apiHost}/api/delete_conversation?id=${id}`, {
      method: 'POST',
    })
      .then(() => {
        fetchConversations();
      })
      .catch((error) => console.error(error));
  };

  const handleDeleteClick = (index: number, doc: Doc) => {
    const docPath = 'indexes/' + 'local' + '/' + doc.name;

    fetch(`${apiHost}/api/delete_old?path=${docPath}`, {
      method: 'GET',
    })
      .then(() => {
        // remove the image element from the DOM
        const imageElement = document.querySelector(
          `#img-${index}`,
        ) as HTMLElement;
        const parentElement = imageElement.parentNode as HTMLElement;
        parentElement.parentNode?.removeChild(parentElement);
      })
      .catch((error) => console.error(error));
  };

  const handleConversationClick = (index: string) => {
    // fetch the conversation from the server and setConversation in the store
    fetch(`${apiHost}/api/get_single_conversation?id=${index}`, {
      method: 'GET',
    })
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

  async function updateConversationName(updatedConversation: {
    name: string;
    id: string;
  }) {
    await fetch(`${apiHost}/api/update_conversation_name`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(updatedConversation),
    })
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
  useOutsideAlerter(
    navRef,
    () => {
      if (isMobile && navOpen && apiKeyModalState === 'INACTIVE') {
        setNavOpen(false);
        setIsDocsListOpen(false);
      }
    },
    [navOpen, isDocsListOpen, apiKeyModalState],
  );

  /*
    Needed to fix bug where if mobile nav was closed and then window was resized to desktop, nav would still be closed but the button to open would be gone, as per #1 on issue #146
  */

  useEffect(() => {
    setNavOpen(!isMobile);
  }, [isMobile]);

  return (
    <>
      {!navOpen && (
        <button
          className="duration-25 absolute sticky top-3 left-3 z-20 hidden transition-all md:block"
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
      )}
      <div
        ref={navRef}
        className={`${
          !navOpen && '-ml-96 md:-ml-[18rem]'
        } duration-20 fixed top-0 z-20 flex h-full w-72 flex-col border-r-2 bg-white transition-all`}
      >
        <div
          className={'visible mt-2 flex h-16 w-full justify-between md:h-12'}
        >
          <div className="my-auto mx-4 flex cursor-pointer gap-1.5">
            <img className="mb-2 h-10" src={DocsGPT3} alt="" />
            <p className="my-auto text-2xl font-semibold">DocsGPT</p>
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
            dispatch(setConversation([]));
            dispatch(
              updateConversationId({
                query: { conversationId: null },
              }),
            );
          }}
          className={({ isActive }) =>
            `${
              isActive ? 'bg-gray-3000' : ''
            } group my-auto mx-4 mt-4 flex cursor-pointer gap-2.5 rounded-3xl border border-silver p-3 hover:border-rainy-gray hover:bg-gray-3000`
          }
        >
          <img
            src={Add}
            alt="new"
            className="opacity-80 group-hover:opacity-100"
          />
          <p className="my-auto text-sm text-dove-gray group-hover:text-neutral-600">
            New Chat
          </p>
        </NavLink>
        {conversations && (
          <div className="conversations-container max-h-[25rem] overflow-y-auto">
            <p className="ml-6 mt-3 text-sm font-semibold">Chats</p>
            {conversations?.map((conversation) => (
              <ConversationTile
                key={conversation.id}
                conversation={conversation}
                selectConversation={(id) => handleConversationClick(id)}
                onDeleteConversation={(id) => handleDeleteConversation(id)}
                onSave={(conversation) => updateConversationName(conversation)}
              />
            ))}
          </div>
        )}

        <div className="flex flex-col-reverse border-b-2">
          <div className="relative my-4 flex gap-2 px-2">
            <div
              className="flex h-12 w-5/6 cursor-pointer justify-between rounded-3xl border-2 bg-white"
              onClick={() => setIsDocsListOpen(!isDocsListOpen)}
            >
              {selectedDocs && (
                <p className="my-3 mx-4 overflow-hidden text-ellipsis whitespace-nowrap">
                  {selectedDocs.name} {selectedDocs.version}
                </p>
              )}
              <img
                src={Arrow2}
                alt="arrow"
                className={`${
                  !isDocsListOpen ? 'rotate-0' : 'rotate-180'
                } ml-auto mr-3 w-3 transition-all`}
              />
            </div>
            <img
              className="mt-2 h-9 w-9 hover:cursor-pointer"
              src={UploadIcon}
              onClick={() => setUploadModalState('ACTIVE')}
            ></img>
            {isDocsListOpen && (
              <div className="absolute top-12 left-0 right-6 ml-2 mr-4 max-h-52 overflow-y-scroll bg-white shadow-lg">
                {docs ? (
                  docs.map((doc, index) => {
                    if (doc.model === embeddingsName) {
                      return (
                        <div
                          key={index}
                          onClick={() => {
                            dispatch(setSelectedDocs(doc));
                            setIsDocsListOpen(false);
                          }}
                          className="flex h-10 w-full cursor-pointer items-center justify-between border-x-2 border-b-2 hover:bg-gray-100"
                        >
                          <p className="ml-5 flex-1 overflow-hidden overflow-ellipsis whitespace-nowrap py-3">
                            {doc.name} {doc.version}
                          </p>
                          {doc.location === 'local' && (
                            <img
                              src={Exit}
                              alt="Exit"
                              className="mr-4 h-3 w-3 cursor-pointer hover:opacity-50"
                              id={`img-${index}`}
                              onClick={(event) => {
                                event.stopPropagation();
                                handleDeleteClick(index, doc);
                              }}
                            />
                          )}
                        </div>
                      );
                    }
                  })
                ) : (
                  <div className="h-10 w-full cursor-pointer border-x-2 border-b-2 hover:bg-gray-100">
                    <p className="ml-5 py-3">No default documentation.</p>
                  </div>
                )}
              </div>
            )}
          </div>
          <p className="ml-6 mt-3 text-sm font-semibold">Source Docs</p>
        </div>
        <div className="flex flex-col gap-2 border-b-2 py-2">
          <div
            className="my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100"
            onClick={() => {
              setApiKeyModalState('ACTIVE');
            }}
          >
            <img src={Key} alt="key" className="ml-2 w-6" />
            <p className="my-auto text-sm text-eerie-black">Reset Key</p>
          </div>
        </div>

        <div className="flex flex-col gap-2 border-b-2 py-2">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              `my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100 ${
                isActive ? 'bg-gray-3000' : ''
              }`
            }
          >
            <img src={SettingGear} alt="info" className="ml-2 w-5 opacity-60" />
            <p className="my-auto text-eerie-black">Settings</p>
          </NavLink>
          <NavLink
            to="/about"
            className={({ isActive }) =>
              `my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100 ${
                isActive ? 'bg-gray-3000' : ''
              }`
            }
          >
            <img src={Info} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-sm text-eerie-black">About</p>
          </NavLink>

          <a
            href="https://docs.docsgpt.co.uk/"
            target="_blank"
            rel="noreferrer"
            className="my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100"
          >
            <img src={Documentation} alt="documentation" className="ml-2 w-5" />
            <p className="my-auto text-sm text-eerie-black">Documentation</p>
          </a>
          <a
            href="https://discord.gg/WHJdfbQDR4"
            target="_blank"
            rel="noreferrer"
            className="my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100"
          >
            <img src={Discord} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-sm text-eerie-black">
              Visit our Discord
            </p>
          </a>

          <a
            href="https://github.com/arc53/DocsGPT"
            target="_blank"
            rel="noreferrer"
            className="my-auto mx-4 flex h-9 cursor-pointer gap-4 rounded-3xl hover:bg-gray-100"
          >
            <img src={Github} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-sm text-eerie-black">Visit our Github</p>
          </a>
        </div>
      </div>
      <div className="fixed z-10 h-16 w-full border-b-2 bg-gray-50 md:hidden">
        <button
          className="mt-5 ml-6 h-6 w-6 md:hidden"
          onClick={() => setNavOpen(true)}
        >
          <img src={Hamburger} alt="menu toggle" className="w-7" />
        </button>
      </div>
      <SelectDocsModal
        modalState={selectedDocsModalState}
        setModalState={setSelectedDocsModalState}
        isCancellable={isSelectedDocsSet}
      />
      <APIKeyModal
        modalState={apiKeyModalState}
        setModalState={setApiKeyModalState}
        isCancellable={isApiKeySet}
      />
      <Upload
        modalState={uploadModalState}
        setModalState={setUploadModalState}
      ></Upload>
    </>
  );
}
