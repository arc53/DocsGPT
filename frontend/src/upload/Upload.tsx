import { useState } from 'react';

export default function Upload() {
  //   return null;

  const [docName, setDocName] = useState('');
  return (
    <article className="absolute z-30  h-screen w-screen  bg-gray-alpha">
      <article className="mx-auto mt-24 flex w-[90vw] max-w-lg  flex-col gap-4 rounded-lg bg-white p-6 shadow-lg">
        <p className="text-xl text-jet">Upload New Documentation</p>
        <input
          type="text"
          className="h-10 w-[60%] rounded-md border-2 border-gray-5000 px-3 outline-none"
          value={docName}
          onChange={(e) => setDocName(e.target.value)}
        ></input>
        <div className="relative bottom-16 left-2">
          <span className="bg-white px-2 text-xs text-gray-4000">Name</span>
        </div>
        <div>
          <label className="rounded-md border border-blue-2000 px-4 py-2 font-medium text-blue-2000">
            <input type="file" className="hidden" />
            Choose Files
          </label>
        </div>
        <div className="flex flex-row-reverse">
          <button className="ml-6 rounded-md bg-blue-3000 py-2 px-6 text-white">
            Train
          </button>
          <button className="font-medium">Cancel</button>
        </div>
      </article>
    </article>
  );
}

// TODO: sanitize all inputs
