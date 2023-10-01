#!/bin/bash

# Function to prompt the user for their choice
prompt_user() {
    echo "Do you want to:"
    echo "1. Download the language model locally (12GB)"
    echo "2. Use the OpenAI API"
    read -p "Enter your choice (1/2): " choice
}

# Function to handle the choice to download the model locally
download_locally() {
    echo "LLM_NAME=llama.cpp" > .env
    echo "VITE_API_STREAMING=true" >> .env
    echo "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" >> .env
    echo "The .env file has been created with LLM_NAME set to llama.cpp."

    # Creating the directory if it does not exist
    mkdir -p models
    
    # Downloading the model to the specific directory
    echo "Downloading the model..."
    # check if docsgpt-7b-f16.gguf does not exist
    if [ ! -f models/docsgpt-7b-f16.gguf ]; then
        echo "Downloading the model..."
        wget -P models https://docsgpt.s3.eu-west-1.amazonaws.com/models/docsgpt-7b-f16.gguf
        echo "Model downloaded to models directory."
    else
        echo "Model already exists."
    fi
   
    docker-compose -f docker-compose-local.yaml build && docker-compose -f docker-compose-local.yaml up -d
    python -m venv venv
    source venv/bin/activate
    pip install -r application/requirements.txt
    pip install llama-cpp-python
    pip install sentence-transformers
    export FLASK_APP=application/app.py
    export FLASK_DEBUG=true
    echo "The application is now running on http://localhost:5173"
    echo "You can stop the application by running the following command:"
    echo "Ctrl + C and then"
    echo "docker-compose down"
    flask run --host=0.0.0.0 --port=7091 &
    celery -A application.app.celery worker -l INFO
}

# Function to handle the choice to use the OpenAI API
use_openai() {
    read -p "Please enter your OpenAI API key: " api_key
    echo "API_KEY=$api_key" > .env
    echo "LLM_NAME=openai" >> .env
    echo "VITE_API_STREAMING=true" >> .env
    echo "The .env file has been created with API_KEY set to your provided key."

    docker-compose build && docker-compose up -d



    echo "The application is will runn on http://localhost:5173"
    echo "You can stop the application by running the following command:"
    echo "docker-compose down"
}

# Prompt the user for their choice
prompt_user

# Handle the user's choice
case $choice in
    1)
        download_locally
        ;;
    2)
        use_openai
        ;;
    *)
        echo "Invalid choice. Please choose either 1 or 2."
        ;;
esac
