import React, { useState } from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';
export default function Login() {
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

    // const response = await fetch(`http://localhost:5000/api/auth/login`, {
    //   method: "POST",
    //   headers: {
    //     "Content-Type": "application/json",
    //   },
    //   body: JSON.stringify({
    //     Email: user.Email,
    //     Password: user.Password,
    //   }),
    // });
    // const json = await response.json();
    // console.log(json);
    // if (json.Check) {
    //   localStorage.setItem("token", json.authtoken);
    //   if (json?.status)
    //   {
    //     localStorage.setItem("isadmin" , true);
    //   }
    //   navigate("/");
    // }
    // else if (!json.Check)
    // {
    //   alert("Invalid Login Credentials")
    //   console.log("Invalid Login Cred")
    // }

    alert('Login Successful ');

    navigate('/');
  };

  const navigate = useNavigate();

  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className=" flex flex-col items-center md:w-fit">
        <div className=" cursor-pointer" onClick={() => navigate('/')}>
          <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        </div>
        <div className="mt-[2vh] flex w-full flex-wrap items-center justify-center gap-2 font-bold ">
          <h1 className="mt-0 text-[4vh] text-white">Log in to</h1>
          <h1 className="mt-0 bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-[4vh] text-transparent">
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
            onChange={(e) => {
              setemail(e.target.value);
            }}
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium text-white focus:outline-none md:min-w-[25vw]"
            // onChange={onchange}
          />
          <input
            type="password"
            name="Name"
            placeholder="Password"
            onChange={(e) => {
              setpassword(e.target.value);
            }}
            className="w-full rounded-lg border-none bg-[#2B2B2B] p-4 text-sm font-medium  text-white focus:outline-none md:min-w-[25vw]"
            // onChange={onchange}
          />
          <h2
            className="text-right text-sm text-[#5F5F5F] hover:cursor-pointer hover:text-white"
            onClick={() => navigate('/Forgot')}
          >
            Forgot your password?
          </h2>
          <button className="h-[7vh] rounded-lg bg-[#7D54D1] font-medium text-white hover:bg-[#8A62DC]">
            Log in
          </button>
          {showalert.length > 0 && (
            <div className="text-red-500">{showalert}</div>
          )}
          <div className="flex w-full justify-center  text-sm">
            <h2 className="flex gap-1 text-right  text-[#5F5F5F]">
              Don&apos;t have an account ?
              <h2
                className="text-center font-medium text-white hover:cursor-pointer hover:underline"
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
