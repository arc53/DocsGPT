import * as React from 'react';
import { useEffect, useState } from 'react';

import Robot from '../../assets/robot.svg';
import { cn } from '@/lib/utils';

type AvatarProps = {
  src?: string | null;
  alt?: string;
  fallbackSrc?: string;
  className?: string;
  imgClassName?: string;
  children?: React.ReactNode;
};

function Avatar({
  src,
  alt = 'agent',
  fallbackSrc = Robot,
  className,
  imgClassName,
  children,
}: AvatarProps) {
  const resolvedSrc = src && src.trim() !== '' ? src : fallbackSrc;
  const [currentSrc, setCurrentSrc] = useState(resolvedSrc);

  useEffect(() => {
    const newSrc = src && src.trim() !== '' ? src : fallbackSrc;
    if (newSrc !== currentSrc) {
      setCurrentSrc(newSrc);
    }
  }, [src, fallbackSrc]);

  return (
    <div data-slot="avatar" className={cn('shrink-0', className)}>
      {children ?? (
        <img
          src={currentSrc}
          alt={alt}
          className={imgClassName}
          referrerPolicy="no-referrer"
          crossOrigin="anonymous"
          onError={() => {
            if (currentSrc !== fallbackSrc) setCurrentSrc(fallbackSrc);
          }}
        />
      )}
    </div>
  );
}

export { Avatar };
