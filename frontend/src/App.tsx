import { Routes, Route, useLocation } from 'react-router-dom';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import About from './About';
import Login from './Login/Login';
import Signup from './Login/Signup';
import ResetCode from './Login/ResetCode';
import ForgotPass from './Login/ForgotPass';

import PageNotFound from './PageNotFound';
import { inject } from '@vercel/analytics';
import { useMediaQuery } from './hooks';
import { useState } from 'react';
import Setting from './Setting';

inject();

export default function App() {
  const { isMobile } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!isMobile);
  const location = useLocation();

  // Checking for the login page
  const isLogin = location.pathname === '/login';

  return (
    <div className="min-h-full min-w-full">
      {!isLogin && <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />}
      <div
        className={`transition-all duration-200  ${
          !isMobile
            ? `ml-0 ${!navOpen ? '-mt-5 md:mx-auto lg:mx-auto' : 'md:ml-72'}`
            : 'ml-0 md:ml-16'
        }${isLogin && `ml-0`}`}
      >
        <Routes>
          <Route path="/" element={<Conversation />} />
          <Route path="/about" element={<About />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Signup />} />
          <Route path="/Forgot" element={<ForgotPass />} />
          <Route path="/ResetPassword" element={<ResetCode />} />
          <Route path="*" element={<PageNotFound />} />
          <Route path="/settings" element={<Setting />} />
        </Routes>
      </div>
    </div>
  );
}
