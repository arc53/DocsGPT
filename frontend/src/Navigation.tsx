import { NavLink } from 'react-router-dom';
import Arrow1 from './assets/arrow.svg';
import Hamburger from './assets/hamburger.svg';
import Key from './assets/key.svg';
import Info from './assets/info.svg';
import Link from './assets/link.svg';
import { ActiveState } from './models/misc';
import APIKeyModal from './preferences/APIKeyModal';
import { useSelector } from 'react-redux';
import { selectApiKeyStatus } from './preferences/preferenceSlice';
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
  const openNav = (
    <div className="fixed z-10 h-full w-72 flex-col border-r-2 border-gray-100 bg-gray-50 transition-all md:visible md:flex lg:w-96">
      <div className={'h-16 w-full border-b-2 border-gray-100'}>
        <button
          className="float-right mr-5 mt-5 h-5 w-5"
          onClick={() => setNavState('INACTIVE')}
        >
          <img
            src={Arrow1}
            alt="menu toggle"
            className={'m-auto w-3 rotate-0 transition-all'}
          />
        </button>
      </div>
      <div className="flex-grow border-b-2 border-gray-100"></div>

      <div className="flex h-16 flex-col border-b-2 border-gray-100">
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
  );

  const closedNav = (
    <>
      <div className="fixed z-10 hidden h-full w-16 flex-col border-r-2 border-gray-100 bg-gray-50 transition-all md:flex">
        <div className={'h-16 w-16 border-b-2 border-gray-100'}>
          <button
            className="float-right mr-5 mt-5 h-5 w-5"
            onClick={() => setNavState('ACTIVE')}
          >
            <img
              src={Arrow1}
              alt="menu toggle"
              className={'m-auto w-3 rotate-180 transition-all'}
            />
          </button>
        </div>
      </div>
      <button
        className="fixed mt-5 ml-6 h-6 w-6 md:hidden"
        onClick={() => setNavState('ACTIVE')}
      >
        <img src={Hamburger} alt="menu toggle" className="w-7" />
      </button>
    </>
  );

  return (
    <>
      {navState === 'ACTIVE' ? openNav : closedNav}
      <APIKeyModal
        modalState={apiKeyModalState}
        setModalState={setApiKeyModalState}
        isCancellable={isApiKeySet}
      />
    </>
  );
}
