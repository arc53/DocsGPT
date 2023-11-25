import React from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';
export default function ResetCode() {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    console.log('login');
  };

  const navigate = useNavigate();
  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className=" flex flex-col items-center px-[5vw] md:w-fit md:p-0">
        <div className=" cursor-pointer" onClick={() => navigate('/')}>
          <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        </div>
        <div className="font-bold md:flex md:gap-2 ">
          <h1 className="text-white">Log in to </h1>
          <h1 className="bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-transparent">
            DocsGPT
          </h1>
        </div>
        <form
          onSubmit={handleSubmit}
          className="flex w-full flex-col gap-[3vh] rounded-2xl border-2 border-[#383838] bg-[#222222] py-[2vh] px-[5vh] text-white md:w-fit"
        >
          <div>
            <h1 className=" text-xl font-semibold md:max-w-[25vw]">
              We&apos;ve sent you instructions to reset your password. Please
              check your inbox.
            </h1>
            <p className="text-md  text-[#888888] md:max-w-[25vw]">
              If you haven&apos;t received an email in 5 minutes, check your
              spam, resend, or try a different email.
            </p>
          </div>
          <input
            type="email"
            name="Name"
            placeholder="Email"
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium text-white focus:outline-none "
            // onChange={onchange}
          />

          <button className="h-[7vh] rounded-lg bg-[#7D54D1] text-sm font-medium text-white hover:bg-[#8A62DC]">
            Request password reset
          </button>
        </form>
        <div className="mt-[2vh] flex w-full justify-center text-sm">
          <h2 className="gap-1 text-right text-[#5F5F5F]  md:flex">
            Don&apos;t have an account ?
            <h2
              className="text-center font-medium text-white hover:cursor-pointer hover:underline"
              onClick={() => navigate('/register')}
            >
              Sign up
            </h2>
          </h2>
        </div>
      </div>
    </div>
  );
}
