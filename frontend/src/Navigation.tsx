import { useEffect, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import Arrow1 from './assets/arrow.svg';
import Arrow2 from './assets/dropdown-arrow.svg';
import Message from './assets/message.svg';
import Hamburger from './assets/hamburger.svg';
import Key from './assets/key.svg';
import Info from './assets/info.svg';
import Link from './assets/link.svg';
import { ActiveState } from './models/misc';
import APIKeyModal from './preferences/APIKeyModal';
import SelectDocsModal from './preferences/SelectDocsModal';
import { useDispatch, useSelector } from 'react-redux';
import {
  selectApiKeyStatus,
  selectSelectedDocs,
  selectSelectedDocsStatus,
  selectSourceDocs,
  setSelectedDocs,
} from './preferences/preferenceSlice';
import { useOutsideAlerter } from './hooks';

export default function Navigation({
  navState,
  setNavState,
}: {
  navState: ActiveState;
  setNavState: React.Dispatch<React.SetStateAction<ActiveState>>;
}) {
  const dispatch = useDispatch();
  const docs = useSelector(selectSourceDocs);
  const selectedDocs = useSelector(selectSelectedDocs);

  const [isDocsListOpen, setIsDocsListOpen] = useState(false);

  const isApiKeySet = useSelector(selectApiKeyStatus);
  const [apiKeyModalState, setApiKeyModalState] = useState<ActiveState>(
    isApiKeySet ? 'INACTIVE' : 'ACTIVE',
  );

  const isSelectedDocsSet = useSelector(selectSelectedDocsStatus);
  const [selectedDocsModalState, setSelectedDocsModalState] =
    useState<ActiveState>(isSelectedDocsSet ? 'INACTIVE' : 'ACTIVE');

  const navRef = useRef(null);
  useOutsideAlerter(
    navRef,
    () => {
      if (
        window.matchMedia('(max-width: 768px)').matches &&
        navState === 'ACTIVE' &&
        apiKeyModalState === 'INACTIVE'
      ) {
        setNavState('INACTIVE');
        setIsDocsListOpen(false);
      }
    },
    [navState, isDocsListOpen, apiKeyModalState],
  );

  /*
    Needed to fix bug where if mobile nav was closed and then window was resized to desktop, nav would still be closed but the button to open would be gone, as per #1 on issue #146
  */
  useEffect(() => {
    window.addEventListener('resize', () => {
      if (window.matchMedia('(min-width: 768px)').matches) {
        setNavState('ACTIVE');
      } else {
        setNavState('INACTIVE');
      }
    });
  }, []);

  return (
    <>
      <div
        ref={navRef}
        className={`${
          navState === 'INACTIVE' && '-ml-96 md:-ml-[14rem]'
        } duration-20 fixed z-20 flex h-full w-72 flex-col border-r-2 bg-gray-50 transition-all`}
      >
        <div className={'visible h-16 w-full border-b-2 md:hidden'}>
          <button
            className="float-right mr-5 mt-5 h-5 w-5"
            onClick={() =>
              setNavState(navState === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE')
            }
          >
            <img
              src={Arrow1}
              alt="menu toggle"
              className={`${
                navState === 'INACTIVE' ? 'rotate-180' : 'rotate-0'
              } m-auto w-3 transition-all duration-200`}
            />
          </button>
        </div>
        <NavLink
          to={'/'}
          className={({ isActive }) =>
            `${
              isActive ? 'bg-gray-3000' : ''
            } my-auto mx-4 mt-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100`
          }
        >
          <img src={Message} className="ml-2 w-5"></img>
          <p className="my-auto text-eerie-black">Chat</p>
        </NavLink>

        <div className="flex-grow border-b-2 border-gray-100"></div>
        <div className="flex flex-col-reverse border-b-2">
          <div className="relative my-4 px-6">
            <div
              className="flex h-12 w-full cursor-pointer justify-between rounded-md border-2 bg-white"
              onClick={() => setIsDocsListOpen(!isDocsListOpen)}
            >
              {selectedDocs && (
                <p className="my-3 mx-4">
                  {selectedDocs.name} {selectedDocs.version}
                </p>
              )}
              <img
                src={Arrow2}
                alt="arrow"
                className={`${
                  isDocsListOpen ? 'rotate-0' : '-rotate-90'
                } mr-3 w-3 transition-all`}
              />
            </div>
            {isDocsListOpen && (
              <div className="absolute top-12 left-0 right-0 mx-6 max-h-52 overflow-y-scroll bg-white shadow-lg">
                {docs ? (
                  docs.map((doc, index) => {
                    if (doc.model) {
                      return (
                        <div
                          key={index}
                          onClick={() => {
                            dispatch(setSelectedDocs(doc));
                            setIsDocsListOpen(false);
                          }}
                          className="h-10 w-full cursor-pointer border-x-2 border-b-2 hover:bg-gray-100"
                        >
                          <p className="ml-5 py-3">
                            {doc.name} {doc.version}
                          </p>
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
          <p className="ml-6 mt-3 font-bold text-jet">Source Docs</p>
        </div>
        <div className="flex flex-col gap-2 border-b-2 py-2">
          <div
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
            onClick={() => {
              setApiKeyModalState('ACTIVE');
            }}
          >
            <img src={Key} alt="key" className="ml-2 w-6" />
            <p className="my-auto text-eerie-black">Reset Key</p>
          </div>
        </div>

        <div className="flex flex-col gap-2 border-b-2 py-2">
          <NavLink
            to="/about"
            className={({ isActive }) =>
              `my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100 ${
                isActive ? 'bg-gray-3000' : ''
              }`
            }
          >
            <img src={Info} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">About</p>
          </NavLink>

          <a
            href="https://discord.gg/WHJdfbQDR4"
            target="_blank"
            rel="noreferrer"
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
          >
            <img src={Link} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Discord</p>
          </a>

          <a
            href="https://github.com/arc53/DocsGPT"
            target="_blank"
            rel="noreferrer"
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
          >
            <img src={Link} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Github</p>
          </a>
        </div>
      </div>
      <div className="fixed h-16 w-full border-b-2 bg-gray-50 md:hidden">
        <button
          className="mt-5 ml-6 h-6 w-6 md:hidden"
          onClick={() => setNavState('ACTIVE')}
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
    </>
  );
}
