import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = (e: { preventDefault: () => void }) => {
    e.preventDefault();

    const data = {
      username: username,
      password: password,
    };

    fetch('http://localhost:5001/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(data),
      mode: 'cors',
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.status === 'ok') {
          navigate('/query');
        } else {
          setError('Invalid username or password');
        }
      })
      .catch((error) => {
        console.error('Error:', error);
      });
  };

  return (
    <>
      {' '}
      <section className="gradient-form h-full justify-center bg-neutral-100 dark:bg-neutral-700">
        <div className="container mx-auto h-full w-7/12 justify-center p-10">
          <div className="g-6 flex h-full flex-wrap items-center justify-center text-neutral-800 dark:text-neutral-200">
            <div className="w-full">
              <div className="block rounded-lg bg-white shadow-lg dark:bg-neutral-800 ">
                <div className="g-0 lg:flex lg:flex-wrap">
                  <div className="loginAbout flex items-center lg:w-5/12 lg:rounded-bl-none"></div>
                  <div className="loginPane justify-center px-4 md:px-0 lg:w-7/12">
                    <div className="md:mx-6 md:p-12">
                      <div className="text-center">
                        <h4 className="loginTitle mb-8 mt-10 pb-1 font-semibold">
                          Document Genius
                        </h4>
                      </div>

                      <p className="text-md mb-8">
                        Welcome to Document Genius!
                      </p>
                      <hr></hr>
                      <div id="loginForm">
                        <form onSubmit={handleSubmit}>
                          <p className="text-md mb-4 mt-8">
                            Login to your account
                          </p>
                          <div
                            className="relative mb-4"
                            data-te-input-wrapper-init
                          >
                            <div
                              className="relative mb-5"
                              data-te-input-wrapper-init
                            >
                              <input
                                className="inputText peer block min-h-[auto] w-full rounded border-2 bg-transparent px-3 py-[0.32rem] leading-[1.6] outline-none focus:placeholder:opacity-100"
                                id="userEmail"
                                type="text"
                                placeholder="Email Address"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                              />
                            </div>
                            <div
                              className="relative mb-5"
                              data-te-input-wrapper-init
                            >
                              <input
                                className="inputText peer block min-h-[auto] w-full rounded border-2 bg-transparent px-3 py-[0.32rem] leading-[1.6] outline-none focus:placeholder:opacity-100"
                                id="userPassword"
                                type="password"
                                placeholder="Password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                              />
                            </div>
                          </div>
                          <div
                            className="relative mb-4"
                            data-te-input-wrapper-init
                          ></div>
                          {error && (
                            <div className="mb-6 text-sm text-red-500">
                              {error}
                            </div>
                          )}
                          <div className="mb-12 pb-1 pt-1 text-center">
                            <button
                              className="loginButton mb-3 inline-block w-full rounded px-6 pb-2 pt-2.5 text-xs font-medium uppercase leading-normal text-white shadow-[0_4px_9px_-4px_rgba(0,0,0,0.2)] transition duration-150 ease-in-out hover:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)] focus:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)] focus:outline-none focus:ring-0 active:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)]"
                              type="submit"
                              data-te-ripple-init
                              data-te-ripple-color="light"
                            >
                              Log In
                            </button>

                            <span className="forgotPassword text-sm">
                              <a href="#!">Forgot password?</a>
                            </span>
                          </div>

                          <div className="flex items-center justify-between pb-6">
                            <p className="mb-0 mr-2">
                              Don&apos;t have an account?
                            </p>
                            <Link to="/register">
                              <button
                                type="button"
                                className="border-danger text-danger hover:border-danger-600 hover:text-danger-600 focus:border-danger-600 focus:text-danger-600 active:border-danger-700 active:text-danger-700 inline-block rounded border-2 px-6 pb-[6px] pt-2 text-xs font-medium uppercase leading-normal transition duration-150 ease-in-out hover:bg-neutral-500 hover:bg-opacity-10 focus:outline-none focus:ring-0 dark:hover:bg-neutral-100 dark:hover:bg-opacity-10"
                              >
                                Register
                              </button>
                            </Link>
                          </div>
                        </form>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
