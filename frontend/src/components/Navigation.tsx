import React, { useState } from 'react';

function MobileNavigation() {
  return <div>Mobile Navigation</div>;
}

function DesktopNavigation() {
  return <div>Desktop Navigation</div>;
}

export default function Navigation({ isMobile }: { isMobile: boolean }) {
  if (isMobile) {
    return <MobileNavigation />;
  } else {
    return <DesktopNavigation />;
  }
}
