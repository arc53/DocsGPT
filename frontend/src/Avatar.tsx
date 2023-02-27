export default function Avatar({
  avatar,
  size,
  className,
}: {
  avatar: string;
  size?: 'SMALL' | 'MEDIUM' | 'LARGE';
  className: string;
}) {
  return <div className={className}>{avatar}</div>;
}
