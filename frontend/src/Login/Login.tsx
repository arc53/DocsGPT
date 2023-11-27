import React, { useState, useEffect } from 'react';
import DocsGPT3 from '../assets/cute_docsgpt3.svg';
import { useNavigate } from 'react-router-dom';
import { IoEye } from 'react-icons/io5';
import { IoMdEyeOff } from 'react-icons/io';
export default function Login() {
  const [showalert, setshowalert] = useState<string>('');
  const [email, setemail] = useState('');
  const [password, setpassword] = useState('');
  const [isVisible, setisVisible] = useState(false);
  const [ispasswordVisible, setispasswordVisible] = useState(false);

  const handleSubmit = () => {
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

  // Toogle Password

  const togglePassword = () => {
    setispasswordVisible(!ispasswordVisible);

    const el = document.getElementById('password') as HTMLInputElement;
    if (el.type === 'password') {
      el.type = 'text';
    } else {
      el.type = 'password';
    }
  };

  useEffect(() => {
    if (password) {
      setisVisible(true);
    } else {
      setisVisible(false);
    }
  }, [password]);

  return (
    <div className="z-30 flex h-full min-h-screen  w-full items-center justify-center bg-[#1D1D1D]">
      <div className="flex flex-col items-center md:w-fit">
        <div className="text- cursor-pointer" onClick={() => navigate('/')}>
          <img src={DocsGPT3} alt="Logo" className="h-[10vh]" />
        </div>
        <div className="mt-[2vh] flex w-full flex-wrap items-center justify-center gap-2 font-bold ">
          <h1 className="mt-0 text-[3vh] text-white md:text-[3.5vh]">
            Log in to
          </h1>
          <h1 className="mt-0 bg-gradient-to-r from-[#56B3CB] via-[#CD2AA0] to-[#EA635C] bg-clip-text text-[3vh] text-transparent md:text-[3.5vh]">
            DocsGPT
          </h1>
        </div>
        <form className="flex w-full flex-col gap-[3vh] md:w-fit">
          <input
            type="email"
            name="Name"
            placeholder="Email"
            onChange={(e) => {
              setemail(e.target.value);
            }}
            className="w-[90vw] cursor-pointer rounded-lg  border-red-400 bg-[#2B2B2B]  p-4 text-sm font-medium text-white hover:bg-[#383838] focus:border-2 focus:border-[#715c9d] focus:outline-none md:w-full  md:min-w-[25vw]"
            // onChange={onchange}
          />
          <div className="relative flex">
            <input
              type="password"
              id="password"
              name="Name"
              placeholder="Password"
              onChange={(e) => {
                setpassword(e.target.value);
              }}
              className="w-[90vw] cursor-pointer rounded-lg  border-red-400 bg-[#2B2B2B]  p-4 text-sm font-medium text-white hover:bg-[#383838] focus:border-2 focus:border-[#715c9d] focus:outline-none md:w-full  md:min-w-[25vw]"
              // onChange={onchange}
            />
            {isVisible &&
              (!ispasswordVisible ? (
                <button
                  onClick={() => togglePassword()}
                  type="button"
                  className="absolute top-[2.2vh] right-[2vh] text-[2vh] text-white md:text-[3vh]"
                >
                  <IoEye />
                </button>
              ) : (
                <button
                  onClick={() => togglePassword()}
                  type="button"
                  className="absolute top-[2.2vh] right-[2vh] text-[2vh] text-white md:text-[3vh]"
                >
                  <IoMdEyeOff />
                </button>
              ))}
          </div>

          <h2
            className="text-right text-sm text-[#5F5F5F] hover:cursor-pointer hover:text-gray-400"
            onClick={() => navigate('/Forgot')}
          >
            Forgot your password?
          </h2>
          <button
            onClick={() => handleSubmit()}
            type="button"
            className="h-[7vh] rounded-lg bg-[#7D54D1] font-semibold text-white hover:bg-[#8A62DC]"
          >
            Log in
          </button>
          {showalert.length > 0 && (
            <div className="text-red-500">{showalert}</div>
          )}
          <div className="flex w-full justify-center  text-sm">
            <h2 className="flex gap-1 text-right  text-[#5F5F5F]">
              Don&apos;t have an account?
              <h2
                className="text-center font-bold text-white hover:cursor-pointer hover:underline"
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
