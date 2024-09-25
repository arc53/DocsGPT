import { ReactNode } from 'react';

export default function Avatar({
  avatar,
  className,
}: {
  avatar: string | ReactNode;
  size?: 'SMALL' | 'MEDIUM' | 'LARGE';
  className: string;
}) {
  return <div className={`${className} flex-shrink-0`}>{avatar}</div>;
}
