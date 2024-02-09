import { Routes, Route } from 'react-router-dom';
import Navigation from './Navigation';
import Conversation from './conversation/Conversation';
import About from './About';
import PageNotFound from './PageNotFound';
import { inject } from '@vercel/analytics';
import { useMediaQuery } from './hooks';
import { useState,useEffect } from 'react';
import Setting from './Setting';

inject();

export default function App() {
  const { isMobile } = useMediaQuery();
  const [navOpen, setNavOpen] = useState(!isMobile);
  return (
    <div className="min-h-full min-w-full dark:bg-raisin-black">
      <Navigation navOpen={navOpen} setNavOpen={setNavOpen} />
      <div
        className={`transition-all duration-200 ${
          !isMobile
            ? `ml-0 ${!navOpen ? '-mt-5 md:mx-auto lg:mx-auto' : 'md:ml-72'}`
            : 'ml-0 md:ml-16'
        }`}
      >
        <Routes>
          <Route path="/" element={<Conversation />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<PageNotFound />} />
          <Route path="/settings" element={<Setting />} />
        </Routes>
      </div>
    </div>
  );
}
