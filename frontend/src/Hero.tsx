export default function Hero({ className = '' }: { className?: string }) {
  return (
    <div className={`mt-14 mb-12 flex flex-col `}>
      <div className="mb-10 flex items-center justify-center ">
        <p className="mr-2 text-4xl font-semibold">DocsGPT</p>
        <p className="text-[27px]">🦖</p>
      </div>
      <p className="mb-3 text-center leading-6 text-black-1000">
        Welcome to DocsGPT, your technical documentation assistant!
      </p>
      <p className="mb-3 text-center leading-6 text-black-1000">
        Enter a query related to the information in the documentation you
        selected to receive
        <br /> and we will provide you with the most relevant answers.
      </p>
      <p className="mb-3 text-center leading-6 text-black-1000">
        Start by entering your query in the input field below and we will do the
        rest!
      </p>
      <div className="sections mt-1 flex flex-wrap items-center justify-center gap-1 sm:gap-1 md:gap-0  ">
        <div className=" rounded-[50px] bg-gradient-to-l from-[#6EE7B7]/70 via-[#3B82F6] to-[#9333EA]/50 p-1  md:rounded-tr-none md:rounded-br-none">
          <div className="h-full rounded-[45px] bg-white p-6 md:rounded-tr-none md:rounded-br-none">
            <img
              src="/message-text.svg"
              alt="lock"
              className="h-[24px] w-[24px]"
            />
            <h2 className="mt-2 mb-3 text-lg font-bold">Chat with Your Data</h2>
            <p className="w-[250px] text-xs text-gray-500">
              DocsGPT will use your data to answer questions. Whether its
              documentation, source code, or Microsoft files, DocsGPT allows you
              to have interactive conversations and find answers based on the
              provided data.
            </p>
          </div>
        </div>

        <div className=" rounded-[50px] bg-gradient-to-r from-[#6EE7B7]/70 via-[#3B82F6] to-[#9333EA]/50 p-1 md:rounded-none  md:py-1 md:px-0">
          <div className="rounded-[45px] bg-white px-6 py-4 md:rounded-none">
            <img src="/lock.svg" alt="lock" className="h-[24px] w-[24px]" />
            <h2 className="mt-2 mb-3 text-lg font-bold">Secure Data Storage</h2>
            <p className=" w-[250px] text-xs text-gray-500">
              The security of your data is our top priority. DocsGPT ensures the
              utmost protection for your sensitive information. With secure data
              storage and privacy measures in place, you can trust that your
              data is kept safe and confidential.
            </p>
          </div>
        </div>
        <div className=" rounded-[50px] bg-gradient-to-l from-[#6EE7B7]/80 via-[#3B82F6] to-[#9333EA]/50 p-1  md:rounded-tl-none md:rounded-bl-none">
          <div className="rounded-[45px] bg-white p-6 px-6 lg:rounded-tl-none lg:rounded-bl-none">
            <img
              src="/message-programming.svg"
              alt="lock"
              className="h-[24px] w-[24px]"
            />
            <h2 className="mt-2 mb-3 text-lg font-bold">Open Source Code</h2>
            <p className=" w-[250px] text-xs text-gray-500">
              DocsGPT is built on open source principles, promoting transparency
              and collaboration. The source code is freely available, enabling
              developers to contribute, enhance, and customize the app to meet
              their specific needs.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
