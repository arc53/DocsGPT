import { ReactNode } from 'react';

export default function Avatar({
  avatar,
  size,
  className,
}: {
  avatar: string | ReactNode;
  size?: 'SMALL' | 'MEDIUM' | 'LARGE';
  className: string;
}) {
  const styles = {
    transform: 'scale(-1, 1)',
  };
  return (
    <div style={styles} className={className}>
      {avatar}
    </div>
  );
}
