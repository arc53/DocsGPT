import { Link } from 'react-router-dom';

export default function Register() {
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
                        Lorem ipsum dolor sit amet, consectetur adipisicing
                        elit, sed do eiusmod tempor incididunt ut labore et
                        dolore magna aliqua. Ut enim ad minim veniam, quis
                        nostrud exercitation ullamco laboris nisi ut aliquip ex
                        ea commodo consequat.
                      </p>
                      <hr></hr>
                      <div id="loginForm">
                        <form>
                          <p className="text-md mb-4 mt-8">
                            Register an account
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
                                type="email"
                                placeholder="Email Address"
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
                              />
                            </div>
                            <div
                              className="relative mb-5"
                              data-te-input-wrapper-init
                            >
                              <input
                                className="inputText peer block min-h-[auto] w-full rounded border-2 bg-transparent px-3 py-[0.32rem] leading-[1.6] outline-none focus:placeholder:opacity-100"
                                id="userPasswordConfirm"
                                type="password"
                                placeholder="Confirm Password"
                              />
                            </div>
                          </div>
                          <div
                            className="relative mb-4"
                            data-te-input-wrapper-init
                          ></div>

                          <div className="mb-8 pb-1 pt-1 text-center">
                            <Link to="/query">
                              <button
                                className="loginButton mb-3 inline-block w-full rounded px-6 pb-2 pt-2.5 text-xs font-medium uppercase leading-normal text-white shadow-[0_4px_9px_-4px_rgba(0,0,0,0.2)] transition duration-150 ease-in-out hover:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)] focus:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)] focus:outline-none focus:ring-0 active:shadow-[0_8px_9px_-4px_rgba(0,0,0,0.1),0_4px_18px_0_rgba(0,0,0,0.2)]"
                                type="button"
                                data-te-ripple-init
                                data-te-ripple-color="light"
                              >
                                Sign Up
                              </button>
                            </Link>
                          </div>

                          <div className="flex items-center justify-between pb-6">
                            <p className="mb-0 mr-2">
                              Already have an account?
                            </p>
                            <Link to="/">
                              <button
                                type="button"
                                className="border-danger text-danger hover:border-danger-600 hover:text-danger-600 focus:border-danger-600 focus:text-danger-600 active:border-danger-700 active:text-danger-700 inline-block rounded border-2 px-6 pb-[6px] pt-2 text-xs font-medium uppercase leading-normal transition duration-150 ease-in-out hover:bg-neutral-500 hover:bg-opacity-10 focus:outline-none focus:ring-0 dark:hover:bg-neutral-100 dark:hover:bg-opacity-10"
                              >
                                Log In
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
