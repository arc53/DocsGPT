export default function Avatar({
  avatar,
  size,
}: {
  avatar: string;
  size?: 'SMALL' | 'MEDIUM' | 'LARGE';
}) {
  return <div>{avatar}</div>;
}
