import React from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';
export default function Login() {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    console.log('login');
  };

  const navigate = useNavigate();

  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className=" flex flex-col items-center md:w-fit">
        <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        <div className="font-bold md:flex md:gap-2">
          <h1 className="text-white">Log in to </h1>
          <h1 className="bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-transparent">
            DocsGPT
          </h1>
        </div>
        <form
          onSubmit={handleSubmit}
          className="flex w-full flex-col gap-[3vh] md:w-fit"
        >
          <input
            type="email"
            name="Name"
            placeholder="Email"
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium text-white focus:outline-none md:min-w-[25vw]"
            // onChange={onchange}
          />
          <input
            type="password"
            name="Name"
            placeholder="Password"
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium  text-white focus:outline-none md:min-w-[25vw]"
            // onChange={onchange}
          />
          <h2
            className="text-right text-sm text-[#5F5F5F] hover:cursor-pointer"
            onClick={() => navigate('/Forgot')}
          >
            Forgot your password?
          </h2>
          <button className="h-[7vh] rounded-lg bg-[#7D54D1] font-medium text-white">
            Log in
          </button>
          <div className="flex w-full justify-center  text-sm">
            <h2 className="flex gap-1 text-right  text-[#5F5F5F]">
              Don&apos;t have an account ?
              <h2
                className="text-center font-medium text-white hover:cursor-pointer"
                onClick={() => navigate('/register')}
              >
                Sign up
              </h2>
            </h2>
          </div>
        </form>
      </div>
    </div>
  );
}
