//TODO - Add hyperlinks to text
//TODO - Styling

export default function About() {
  return (
    <div className="mx-5 grid min-h-screen md:mx-36">
      <article className=" place-items-left mx-auto my-auto flex w-full max-w-6xl flex-col gap-6 rounded-lg bg-gray-100 p-6 pt-14 pb-14 text-jet lg:p-10 xl:p-16">
        <div className="flex items-center">
          <p className="mr-2 text-3xl">About DocsGPT</p>
          <p className="text-[21px]">🦖</p>
        </div>
        <p className="mt-4">
          Find the information in your documentation through AI-powered
          <a
            className="text-blue-500"
            href="https://github.com/arc53/DocsGPT"
            target="_blank"
            rel="noreferrer"
          >
            {' '}
            open-source{' '}
          </a>
          chatbot. Powered by GPT-3, Faiss and LangChain.
        </p>

        <div>
          <p>
            If you want to add your own documentation, please follow the
            instruction below:
          </p>
          <p className="mt-4 ml-2">
            1. Navigate to{' '}
            <span className="bg-gray-200 italic"> /application</span> folder
          </p>
          <p className="mt-4 ml-2">
            2. Install dependencies from{' '}
            <span className="bg-gray-200 italic">
              pip install -r requirements.txt
            </span>
          </p>
          <p className="mt-4 ml-2">
            3. Prepare a <span className="bg-gray-200 italic">.env</span> file.
            Copy <span className="bg-gray-200 italic">.env_sample</span> and
            create <span className="bg-gray-200 italic">.env</span> with your
            OpenAI API token
          </p>
          <p className="mt-4 ml-2">
            4. Run the app with{' '}
            <span className="bg-gray-200 italic">python app.py</span>
          </p>
        </div>

        <p>
          Currently It uses DocsGPT documentation, so it will respond to
          information relevant to DocsGPT. If you want to train it on different
          documentation - please follow
          <a
            className="text-blue-500"
            href="https://github.com/arc53/DocsGPT/wiki/How-to-train-on-other-documentation"
            target="_blank"
            rel="noreferrer"
          >
            {' '}
            this guide
          </a>
          .
        </p>

        <p className="mt-4 text-left">
          If you want to launch it on your own server - follow
          <a
            className="text-blue-500"
            href="https://github.com/arc53/DocsGPT/wiki/Hosting-the-app"
            target="_blank"
            rel="noreferrer"
          >
            {' '}
            this guide
          </a>
          .
        </p>
      </article>
    </div>
  );
}
