import { useDispatch, useSelector } from 'react-redux';
import { NavLink } from 'react-router-dom';
import { useMediaQuery } from '../hooks';
import { toggleApiKeyModal } from '../store';
import Arrow1 from '../imgs/arrow.svg';
import Hamburger from '../imgs/hamburger.svg';
import Key from '../imgs/key.svg';
import Info from '../imgs/info.svg';
import Link from '../imgs/link.svg';
import Exit from '../imgs/exit.svg';
import { NavState } from '../models/misc';

//TODO - Need to replace Chat button to open secondary nav with scrollable past chats option and new chat at top
//TODO - Need to add Discord and Github links

export default function Navigation({
  navState,
  setNavState,
}: {
  navState: NavState;
  setNavState: (val: NavState) => void;
}) {
  const openNav = (
    <div className="fixed h-full w-72 flex-col border-r-2 border-gray-100 bg-gray-50 transition-all md:visible md:flex lg:w-96">
      <div className={'h-16 w-full border-b-2 border-gray-100'}>
        <button
          className="float-right mr-5 mt-5 h-5 w-5"
          onClick={() => setNavState('CLOSED')}
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
            return;
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
      <div className="fixed hidden h-full w-16 flex-col border-r-2 border-gray-100 bg-gray-50 transition-all md:flex">
        <div className={'h-16 w-16 border-b-2 border-gray-100'}>
          <button
            className="float-right mr-5 mt-5 h-5 w-5"
            onClick={() => setNavState('OPEN')}
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
        onClick={() => setNavState('OPEN')}
      >
        <img src={Hamburger} alt="menu toggle" className="w-7" />
      </button>
    </>
  );

  return navState === 'OPEN' ? openNav : closedNav;
}
