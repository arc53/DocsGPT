import React, { useState } from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';

export default function Signup() {
  const [showalert, setshowalert] = useState<string>('');
  const [email, setemail] = useState('');
  const [password, setpassword] = useState('');

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    //email validation
    if (email.length === 0 || password.length === 0) {
      if (password.length === 0) {
        setshowalert('Password is required');
        return;
      } else {
        setshowalert('Email is required');
      }
      return;
    } else {
      setshowalert('');
    }
    if (password.length === 0) {
      setshowalert('Password is required');
      return;
    }

    alert('Signup Successful ');

    navigate('/login');
  };

  const navigate = useNavigate();

  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className=" flex flex-col items-center md:w-fit">
        <div className=" cursor-pointer" onClick={() => navigate('/')}>
          <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        </div>
        <div className="font-bold md:flex md:gap-2">
          <h1 className="text-white">Create</h1>
          <h1 className="bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-transparent">
            DocsGPT
          </h1>
          <h1 className="text-white">Account</h1>
        </div>
        <form
          onSubmit={handleSubmit}
          className="flex w-full flex-col gap-[3vh] md:w-fit"
        >
          <input
            type="email"
            name="Name"
            placeholder="Email"
            onChange={(e) => {
              setemail(e.target.value);
            }}
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium text-white focus:outline-none md:min-w-[25vw]"
          />
          <input
            type="password"
            name="Name"
            placeholder="Password"
            onChange={(e) => {
              setpassword(e.target.value);
            }}
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium  text-white focus:outline-none md:min-w-[25vw]"
          />
          <button className="h-[7vh] rounded-lg bg-[#7D54D1] font-medium text-white">
            Create Account
          </button>
          {showalert.length > 0 && (
            <div className="text-red-500">{showalert}</div>
          )}
          <div className="flex w-full justify-center  text-sm">
            <h2 className="flex gap-1 text-right  text-[#5F5F5F]">
              Already have an account ?
              <h2
                className="text-center font-medium text-white hover:cursor-pointer"
                onClick={() => navigate('/login')}
              >
                log in
              </h2>
            </h2>
          </div>
        </form>
      </div>
    </div>
  );
}
