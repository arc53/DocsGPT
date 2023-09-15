# Self-hosting DocsGPT on Amazon Lightsail

Here's a step-by-step guide on how to setup an Amazon Lightsail instance to host DocsGPT.

## Configuring your instance

(If you know how to create a Lightsail instance, you can skip to the recommended configuration part by clicking here)

### 1. Create an account or login to https://lightsail.aws.amazon.com

### 2. Click on "Create instance"

### 3. Create your instance

The first step is to select the "Instance location". In most cases there's no need to switch locations as the default one will work well.

After that it is time to pick your Instance Image. We recommend using "Linux/Unix" as the image and "Ubuntu 20.04 LTS" for Operating System.

As for instance plan, it'll vary depending on your unique demands, but a "1 GB, 1vCPU, 40GB SSD and 2TB transfer" setup should cover most scenarios.

Lastly, Identify your instance by giving it a unique name and then hit "Create instance".

PS: Once you create your instance, it'll likely take a few minutes for the setup to be completed.

#### The recommended configuration is as follows:

- Ubuntu 20.04 LTS
- 1GB RAM
- 1vCPU
- 40GB SSD Hard Drive
- 2TB transfer

### Connecting to your the newly created instance

Your instance will be ready for use a few minutes after being created. To access, just open it up and click on "Connect using SSH".

#### Clone the repository

A terminal window will pop up, and the first step will be to clone DocsGPT git repository.

`git clone https://github.com/arc53/DocsGPT.git`

#### Download the package information

Once it has finished cloning the repository, it is time to download the package information from all sources. To do so simply enter the following command:

`sudo apt update`

#### Install Docker and Docker Compose

DocsGPT backend and worker use python, Frontend is written on React and the whole application is containerized using Docker. To install Docker and Docker Compose, enter the following commands:

`sudo apt install docker.io`

And now install docker-compose:

`sudo apt install docker-compose`

#### Access the DocsGPT folder

Enter the following command to access the folder in which DocsGPT docker-compose file is.

`cd DocsGPT/`

#### Prepare the environment

Inside the DocsGPT folder create a .env file and copy the contents of .env_sample into it.

`nano .env`

Make sure your .env file looks like this:

```
OPENAI_API_KEY=(Your OpenAI API key)
VITE_API_STREAMING=true
SELF_HOSTED_MODEL=false
```

To save the file, press CTRL+X, then Y and then ENTER.

Next we need to set a correct IP for our Backend. To do so, open the docker-compose.yml file:

`nano docker-compose.yml`

And change this line 7 `VITE_API_HOST=http://localhost:7091`
to this `VITE_API_HOST=http://<your instance public IP>:7091`

This will allow the frontend to connect to the backend.

#### Running the app

You're almost there! Now that all the necessary bits and pieces have been installed, it is time to run the application. To do so, use the following command:

`sudo docker-compose up -d`

If you launch it for the first time it will take a few minutes to download all the necessary dependencies and build.

Once this is done you can go ahead and close the terminal window.

#### Enabling ports 

Before you being able to access your live instance, you must first enable the port which it is using.

Open your Lightsail instance and head to "Networking".

Then click on "Add rule" under "IPv4 Firewall", enter 5173 as your your port and hit "Create". 
Repeat the process for port 7091.

#### Access your instance

Your instance will now be available under your Public IP Address and port 5173. Enjoy!

