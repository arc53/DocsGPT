import React, { useState } from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';

export default function Signup() {
  const [showalert, setshowalert] = useState<string>('');
  const [email, setemail] = useState('');
  const [password, setpassword] = useState('');

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    if (email.length === 0 || password.length === 0) {
      setshowalert('Both fields are required');
      return;
    }

    //email validation
    if (!email.match(/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/)) {
      setshowalert('Please enter a valid email address');
      return;
    }

    setshowalert('');
    alert('Signup Successful ');

    navigate('/login');
  };

  const navigate = useNavigate();

  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className=" flex flex-col items-center px-[5vh] md:w-fit md:px-0">
        <div className=" cursor-pointer" onClick={() => navigate('/')}>
          <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        </div>
        <div className="mt-[2vh] flex flex-wrap items-center justify-center gap-2 font-bold ">
          <h1 className="mt-0 text-[3vh] text-white md:text-[3.5vh]">Create</h1>
          <h1 className="mt-0 bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-[3vh] text-transparent md:text-[3.5vh]">
            DocsGPT
          </h1>
          <h1 className="mt-0 text-[3vh] text-white md:text-[3.5vh]">
            Account
          </h1>
        </div>
        <form
          onSubmit={handleSubmit}
          className="flex flex-col gap-[3vh] px-[2vh] md:w-fit"
        >
          <input
            type="email"
            name="Name"
            placeholder="Email"
            onChange={(e) => {
              setemail(e.target.value);
            }}
            className="w-[90vw] cursor-pointer rounded-lg  border-red-400 bg-[#2B2B2B]  p-4 text-sm font-medium text-white hover:bg-[#383838] focus:border-2 focus:border-[#715c9d] focus:outline-none md:w-full  md:min-w-[25vw]"
          />
          <input
            type="password"
            name="Name"
            placeholder="Password"
            onChange={(e) => {
              setpassword(e.target.value);
            }}
            className="w-[90vw] cursor-pointer rounded-lg  border-red-400 bg-[#2B2B2B]  p-4 text-sm font-medium text-white hover:bg-[#383838] focus:border-2 focus:border-[#715c9d] focus:outline-none md:w-full  md:min-w-[25vw]"
          />
          <button className="h-[7vh] rounded-lg bg-[#7D54D1] font-semibold text-white hover:bg-[#8A62DC]">
            Create Account
          </button>
          {showalert.length > 0 && (
            <div className="text-red-500">{showalert}</div>
          )}
          <div className="flex w-full justify-center  text-sm">
            <h2 className="flex gap-1 text-right  text-[#5F5F5F]">
              Already have an account?
              <h2
                className="text-center font-bold text-white hover:cursor-pointer hover:underline"
                onClick={() => navigate('/login')}
              >
                Log in
              </h2>
            </h2>
          </div>
        </form>
      </div>
    </div>
  );
}
