export default function Hero({ className = '' }: { className?: string }) {
  return (
    <div className={`flex flex-col ${className}`}>
      <p className="mb-10 text-center text-4xl font-semibold">
        DocsGPT <span className="text-3xl">🦖</span>
      </p>
      <p className="mb-3 text-center text-gray-2000">
        Welcome to DocsGPT, your technical documentation assistant!
      </p>
      <p className="mb-3 text-center text-gray-2000">
        Enter a query related to the information in the documentation you
        selected to receive and we will provide you with the most relevant
        answers.
      </p>
      <p className="text-center text-gray-2000">
        Start by entering your query in the input field below and we will do the
        rest!
      </p>
    </div>
  );
}
