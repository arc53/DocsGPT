import { NavLink } from 'react-router-dom';
import Arrow1 from './assets/arrow.svg';
import Hamburger from './assets/hamburger.svg';
import Key from './assets/key.svg';
import Info from './assets/info.svg';
import Link from './assets/link.svg';
import { ActiveState } from './models/misc';
import APIKeyModal from './preferences/APIKeyModal';
import SelectDocsModal from './preferences/SelectDocsModal';
import { useSelector } from 'react-redux';
import {
  selectApiKeyStatus,
  selectSelectedDocsStatus,
} from './preferences/preferenceSlice';
import { useState } from 'react';

//TODO - Need to replace Chat button to open secondary nav with scrollable past chats option and new chat at top
//TODO - Need to add Discord and Github links

export default function Navigation({
  navState,
  setNavState,
}: {
  navState: ActiveState;
  setNavState: (val: ActiveState) => void;
}) {
  const isApiKeySet = useSelector(selectApiKeyStatus);
  const [apiKeyModalState, setApiKeyModalState] = useState<ActiveState>(
    isApiKeySet ? 'INACTIVE' : 'ACTIVE',
  );

  const isSelectedDocsSet = useSelector(selectSelectedDocsStatus);
  const [selectedDocsModalState, setSelectedDocsModalState] =
    useState<ActiveState>(isSelectedDocsSet ? 'INACTIVE' : 'ACTIVE');

  return (
    <>
      <div
        className={`${
          navState === 'INACTIVE' && '-ml-96 md:-ml-60 lg:-ml-80'
        } fixed z-10 flex h-full w-72 flex-col border-r-2 border-gray-100 bg-gray-50 transition-all duration-200 lg:w-96`}
      >
        <div className={'h-16 w-full border-b-2 border-gray-100'}>
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
              }  m-auto w-3 transition-all duration-200`}
            />
          </button>
        </div>
        <div className="flex-grow border-b-2 border-gray-100"></div>

        <div className="flex flex-col gap-2 border-b-2 border-gray-100 py-2">
          <div
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
            onClick={() => {
              setApiKeyModalState('ACTIVE');
            }}
          >
            <img src={Key} alt="key" className="ml-2 w-6" />
            <p className="my-auto text-eerie-black">Reset Key</p>
          </div>

          <div
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
            onClick={() => {
              setSelectedDocsModalState('ACTIVE');
            }}
          >
            <img src={Link} alt="key" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">
              Select Source Documentation
            </p>
          </div>
        </div>

        <div className="flex h-48 flex-col border-b-2 border-gray-100">
          <NavLink
            to="/about"
            className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100"
          >
            <img src={Info} alt="info" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">About</p>
          </NavLink>

          <div className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100">
            <img src={Link} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Discord</p>
          </div>

          <div className="my-auto mx-4 flex h-12 cursor-pointer gap-4 rounded-md hover:bg-gray-100">
            <img src={Link} alt="link" className="ml-2 w-5" />
            <p className="my-auto text-eerie-black">Github</p>
          </div>
        </div>
      </div>
      <button
        className="fixed mt-5 ml-6 h-6 w-6 md:hidden"
        onClick={() => setNavState('ACTIVE')}
      >
        <img src={Hamburger} alt="menu toggle" className="w-7" />
      </button>

      <APIKeyModal
        modalState={apiKeyModalState}
        setModalState={setApiKeyModalState}
        isCancellable={isApiKeySet}
      />
      <SelectDocsModal
        modalState={selectedDocsModalState}
        setModalState={setSelectedDocsModalState}
        isCancellable={isSelectedDocsSet}
      />
    </>
  );
}
