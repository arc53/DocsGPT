import { Link } from 'react-router-dom';

export default function PageNotFound() {
  return (
    <div className="dark:bg-raisin-black grid min-h-screen">
      <p className="text-jet dark:bg-outer-space mx-auto my-auto mt-20 flex w-full max-w-6xl flex-col place-items-center gap-6 rounded-3xl bg-gray-100 p-6 lg:p-10 xl:p-16 dark:text-gray-100">
        <h1>404</h1>
        <p>The page you are looking for does not exist.</p>
        <button className="pointer-cursor bg-blue-1000 hover:bg-blue-3000 mr-4 flex cursor-pointer items-center justify-center rounded-full px-4 py-2 text-white transition-colors duration-100">
          <Link to="/">Go Back Home</Link>
        </button>
      </p>
    </div>
  );
}
