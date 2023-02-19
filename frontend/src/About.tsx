//TODO - Add hyperlinks to text
//TODO - Styling

export default function About() {
  return (
    //Parent div for all content shown through App.tsx routing needs to have this styling. Might change when state management is updated.
    <div className="mx-6 grid min-h-screen">
      <article className=" mx-auto my-auto flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-lg bg-gray-100 p-6 text-jet lg:p-10 xl:p-16">
        <p className="text-3xl font-semibold">About DocsGPT 🦖</p>
        <p className="mt-4 text-xl font-bold">
          Find the information in your documentation through AI-powered
          open-source chatbot. Powered by GPT-3, Faiss and LangChain.
        </p>

        <div>
          <p className="text-lg">
            If you want to add your own documentation, please follow the
            instruction below:
          </p>
          <p className="mt-4 text-lg">
            1. Navigate to{' '}
            <span className="bg-gray-200 italic"> /application</span> folder
          </p>
          <p className="mt-4 text-lg">
            2. Install dependencies from{' '}
            <span className="bg-gray-200 italic">
              pip install -r requirements.txt
            </span>
          </p>
          <p className="mt-4 text-lg">
            3. Prepare a <span className="bg-gray-200 italic">.env</span> file.
            Copy <span className="bg-gray-200 italic">.env_sample</span> and
            create <span className="bg-gray-200 italic">.env</span> with your
            OpenAI API token
          </p>
          <p className="mt-4 text-lg">
            4. Run the app with{' '}
            <span className="bg-gray-200 italic">python app.py</span>
          </p>
        </div>

        <p className="text-lg">
          Currently It uses python pandas documentation, so it will respond to
          information relevant to pandas. If you want to train it on different
          documentation - please follow this guide.
        </p>

        <p className="mt-4 text-lg">
          If you want to launch it on your own server - follow this guide.
        </p>
      </article>
    </div>
  );
}
