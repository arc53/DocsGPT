export default function Avatar({
  avatar,
  size,
}: {
  avatar: string;
  size?: 'SMALL' | 'MEDIUM' | 'LARGE';
}) {
  return <div className={'mt-4 text-2xl'}>{avatar}</div>;
}
