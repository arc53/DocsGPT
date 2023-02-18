import Send from './../assets/send.svg';

export default function ConversationInput({
  className,
}: {
  className?: string;
}) {
  return (
    <div className={`${className} flex`}>
      <div
        contentEditable
        className={`min-h-5 border-000000 overflow-x-hidden; max-h-24 w-full overflow-y-auto rounded-xl border bg-white p-2 pr-9 opacity-100 focus:border-2 focus:outline-none`}
      ></div>
      <img
        onClick={() => console.log('here')}
        src={Send}
        className="relative right-9"
      ></img>
    </div>
  );
}
