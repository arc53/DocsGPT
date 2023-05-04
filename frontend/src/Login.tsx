import { Link } from 'react-router-dom';

export default function Login() {
  return (
    <div className="p-5">
      <div className="gap-6 rounded-lg bg-gray-100 text-jet">
        <div className={`flex flex-col`}>
          <div className="mb-10 flex items-center justify-center">
            <p className="mr-2 text-4xl font-semibold">Document Genius</p>
          </div>
          <p className="mb-3 text-center leading-4 text-black-1000">
            Login and File Upload to go here
          </p>
          <p className="mb-3 text-center leading-6 text-black-1000">
            <Link to="/query">
              <b>To Query Page</b>
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
