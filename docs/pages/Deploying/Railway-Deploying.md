
# Self-hosting DocsGPT on Railway

  

Here's a step-by-step guide on how to host DocsGPT on Railway App.

  

At first Clone and set up the project locally to run , test and Modify.

  

### 1. Clone and GitHub SetUp

a. Open Terminal (Windows Shell or Git bash(recommended)).

  

b. Type `git clone https://github.com/arc53/DocsGPT.git`

  

#### Download the package information

  

Once it has finished cloning the repository, it is time to download the package information from all sources. To do so, simply enter the following command:

  

`sudo apt update`

  

#### Install Docker and Docker Compose

  

DocsGPT backend and worker use Python, Frontend is written on React and the whole application is containerized using Docker. To install Docker and Docker Compose, enter the following commands:

  

`sudo apt install docker.io`

  

And now install docker-compose:

  

`sudo apt install docker-compose`

  

#### Access the DocsGPT Folder

  

Enter the following command to access the folder in which the DocsGPT docker-compose file is present.

  

`cd DocsGPT/`

  

#### Prepare the Environment

  

Inside the DocsGPT folder create a `.env` file and copy the contents of `.env_sample` into it.

  

`nano .env`

  

Make sure your `.env` file looks like this:

  

```

OPENAI_API_KEY=(Your OpenAI API key)

VITE_API_STREAMING=true

SELF_HOSTED_MODEL=false

```

  

To save the file, press CTRL+X, then Y, and then ENTER.

  

Next, set the correct IP for the Backend by opening the docker-compose.yml file:

  

`nano docker-compose.yml`

  

And Change line 7 to: `VITE_API_HOST=http://localhost:7091`

to this `VITE_API_HOST=http://<your instance public IP>:7091`

  

This will allow the frontend to connect to the backend.

  

#### Running the Application

  

You're almost there! Now that all the necessary bits and pieces have been installed, it is time to run the application. To do so, use the following command:

  

`sudo docker-compose up -d`

  

Launching it for the first time will take a few minutes to download all the necessary dependencies and build.

  

Once this is done you can go ahead and close the terminal window.

  

### 2. Pushing it to your own Repository

  

a. Create a Repository on your GitHub.

  

b. Open Terminal in the same directory of the Cloned project.

  

c. Type `git init`

  

d. `git add .`

  

e. `git commit -m "first-commit"`

  

f. `git remote add origin <your  repository  link>`

  

g. `git push git push --set-upstream origin master`

Your local files will now be pushed to your GitHub Account. :)
  

### 3. Create a Railway Account:

  

If you haven't already, create or log in to your railway account do it by visiting [Railway](https://railway.app/)

  

Signup via **GitHub** [Recommended].

  

### 4. Start New Project:

  

a. Open Railway app and Click on "Start New Project."

  

b. Choose any from the list of options available (Recommended "**Deploy from GitHub Repo**")

  

c. Choose the required Repository from your GitHub.

  

d. Configure and allow access to modify your GitHub content from the pop-up window.

  

e. Agree to all the terms and conditions.

  

PS: It may take a few minutes for the account setup to complete.

  

#### You will get A free trial of $5 (use it for trial and then purchase if satisfied and needed)

  

### 5. Connecting to Your newly Railway app with GitHub

  

a. Choose DocsGPT repo from the list of your GitHub repository that you want to deploy now.

  

b. Click on Deploy now.

  

![Three Tabs will be there](/Railway-selection.png)

  

c. Select Variables Tab.

  

d. Upload the env file here that you used for local setup.

  

e. Go to Settings Tab now.

  

f. Go to "Networking" and click on Generate Domain Name, to get the URL of your hosted project.

  

g. You can update the Root directory, build command, installation command as per need.

*[However recommended not the disturb these options and leave them as default if not that needed.]*

  
  

Your own DocsGPT is now available at the Generated domain URl. :)
