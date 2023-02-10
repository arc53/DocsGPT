import React, { useState } from 'react';
import Arrow1 from './imgs/arrow.svg';

function MobileNavigation() {
  return <div>Mobile Navigation</div>;
}

function DesktopNavigation() {
  return (
    <div className="fixed h-screen w-72 border-r-2 border-gray-100 bg-gray-50 lg:w-96">
      <div className="h-16 border-b-2 border-gray-100">
        <button className="float-right mr-4 mt-5 h-5 w-5">
          <img src={Arrow1} alt="menu toggle" className="m-auto w-3" />
        </button>
      </div>
    </div>
  );
}

export default function Navigation({ isMobile }: { isMobile: boolean }) {
  if (isMobile) {
    return <MobileNavigation />;
  } else {
    return <DesktopNavigation />;
  }
}
