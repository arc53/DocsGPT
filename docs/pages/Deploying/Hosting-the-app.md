# Self-hosting DocsGPT on Amazon Lightsail

Here's a step-by-step guide on how to setup an Amazon Lightsail instance to host DocsGPT.

## Configuring your instance

(If you know how to create a Lightsail instance, you can skip to the recommended configuration part by clicking here).

### 1. Create an AWS Account: 
If you haven't already, create or log in to your AWS account at lightsail.aws.amazon.com.

### 2. Create an Instance: 

a. Click "Create Instance."

b. Select the "Instance location." In most cases, the default location works fine.

c. Choose "Linux/Unix" as the image and "Ubuntu 20.04 LTS" as the Operating System.

d. Configure the instance plan based on your requirements. A "1 GB, 1vCPU, 40GB SSD, and 2TB transfer" setup is recommended for most scenarios.

e. Give your instance a unique name and click "Create Instance."

PS: It may take a few minutes for the instance setup to complete.

### Connecting to Your newly created Instance

Your instance will be ready a few minutes after creation. To access it, open the instance and click "Connect using SSH."

#### Clone the DocsGPT Repository

A terminal window will pop up, and the first step will be to clone the DocsGPT Git repository:

`git clone https://github.com/arc53/DocsGPT.git`

#### Download the package information

Once it has finished cloning the repository, it is time to download the package information from all sources. To do so simply enter the following command:

`sudo apt update`

#### Installing Docker and Docker Compose

DocsGPT backend and worker use Python, Frontend is written on React and the whole application is containerized using Docker. To install Docker and Docker Compose, enter the following commands:

`sudo apt install docker.io`

And now install docker-compose:

`sudo apt install docker-compose`

#### Access the DocsGPT Folder

Enter the following command to access the folder in which DocsGPT docker-compose file is present.

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

#### Enabling Ports 

a. Before you are able to access your live instance, you must first enable the port that it is using.

b. Open your Lightsail instance and head to "Networking".

c. Then click on "Add rule" under "IPv4 Firewall", enter `5173` as your port, and hit "Create". 
Repeat the process for port `7091`.

#### Access your instance

Your instance is now available at your Public IP Address on port 5173. Enjoy using DocsGPT!
