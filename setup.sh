#!/bin/bash

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DEFAULT_FG='\033[39m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

# Base Compose file (relative to script location)
COMPOSE_FILE="$(dirname "$(readlink -f "$0")")/deployment/docker-compose.yaml"
ENV_FILE="$(dirname "$(readlink -f "$0")")/.env"

# Animation function
animate_dino() {
    tput civis  # Hide cursor
    local dino_lines=(
        "                                     #########      "
        "                                   #############    "
        "                                  ##################"
        "                                ####################"
        "                              ######################"
        "                    #######################   ######"
        "                 ###############################    "
        "              ##################################    "
        "            ################ ############           "
        "           ################## ##########            "
        "         ##################### ########             "
        "        ###################### ###### ###           "
        "      ############  ##########    #### ##           "
        "     #############  #########       #####           "
        "   ##############  #########                        "
        " ############## ##########                          "
        "############    #######                             "
        " ######         ######   ####                       "
        "                ################                    "
        "                #################                   "
    )

    # Static DocsGPT text
    local static_text=(
        "  ____                  ____ ____ _____ "
        " |  _ \\  ___   ___ ___ / ___|  _ \\_   _|"
        " | | | |/ _ \\ / __/ __| |  _| |_) || |  "
        " | |_| | (_) | (__\\__ \\ |_| |  __/ | |  "
        " |____/ \\___/ \\___|___/\\____|_|    |_|  "
        "                                        "
    )

    # Print static text
    clear
    for line in "${static_text[@]}"; do
        echo "$line"
    done

    tput sc

    # Build-up animation
    for i in "${!dino_lines[@]}"; do
        tput rc
        for ((j=0; j<=i; j++)); do
            echo "${dino_lines[$j]}"
        done
        sleep 0.05
    done

    sleep 0.5

    tput rc
    tput ed

    tput cnorm
}

# Check and start Docker function
check_and_start_docker() {
    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        echo "Docker is not running. Starting Docker..."

        # Check the operating system
        case "$(uname -s)" in
            Darwin)
                open -a Docker
                ;;
            Linux)
                sudo systemctl start docker
                ;;
            *)
                echo "Unsupported platform. Please start Docker manually."
                exit 1
                ;;
        esac

        # Wait for Docker to be fully operational with animated dots
        echo -n "Waiting for Docker to start"
        while ! docker system info > /dev/null 2>&1; do
            for i in {1..3}; do
                echo -n "."
                sleep 1
            done
            echo -ne "\rWaiting for Docker to start   "
        done

        echo -e "\nDocker has started!"
    fi
}

# Function to prompt the user for the main menu choice
prompt_main_menu() {
    echo -e "\n${DEFAULT_FG}${BOLD}Welcome to DocsGPT Setup!${NC}"
    echo -e "${DEFAULT_FG}How would you like to proceed?${NC}"
    echo -e "${YELLOW}1) Use DocsGPT Public API Endpoint (simple and free)${NC}"
    echo -e "${YELLOW}2) Serve Local (with Ollama)${NC}"
    echo -e "${YELLOW}3) Connect Local Inference Engine${NC}"
    echo -e "${YELLOW}4) Connect Cloud API Provider${NC}"
    echo
    read -p "$(echo -e "${DEFAULT_FG}Choose option (1-4): ${NC}")" main_choice
}

# Function to prompt for Local Inference Engine options
prompt_local_inference_engine_options() {
    clear
    echo -e "\n${DEFAULT_FG}${BOLD}Connect Local Inference Engine${NC}"
    echo -e "${DEFAULT_FG}Choose your local inference engine:${NC}"
    echo -e "${YELLOW}1) LLaMa.cpp${NC}"
    echo -e "${YELLOW}2) Ollama${NC}"
    echo -e "${YELLOW}3) Text Generation Inference (TGI)${NC}"
    echo -e "${YELLOW}4) SGLang${NC}"
    echo -e "${YELLOW}5) vLLM${NC}"
    echo -e "${YELLOW}6) Aphrodite${NC}"
    echo -e "${YELLOW}7) FriendliAI${NC}"
    echo -e "${YELLOW}8) LMDeploy${NC}"
    echo -e "${YELLOW}b) Back to Main Menu${NC}"
    echo
    read -p "$(echo -e "${DEFAULT_FG}Choose option (1-8, or b): ${NC}")" engine_choice
}

# Function to prompt for Cloud API Provider options
prompt_cloud_api_provider_options() {
    clear
    echo -e "\n${DEFAULT_FG}${BOLD}Connect Cloud API Provider${NC}"
    echo -e "${DEFAULT_FG}Choose your Cloud API Provider:${NC}"
    echo -e "${YELLOW}1) OpenAI${NC}"
    echo -e "${YELLOW}2) Google (Vertex AI, Gemini)${NC}"
    echo -e "${YELLOW}3) Anthropic (Claude)${NC}"
    echo -e "${YELLOW}4) Groq${NC}"
    echo -e "${YELLOW}5) HuggingFace Inference API${NC}"
    echo -e "${YELLOW}6) Azure OpenAI${NC}"
    echo -e "${YELLOW}7) Novita${NC}"
    echo -e "${YELLOW}b) Back to Main Menu${NC}"
    echo
    read -p "$(echo -e "${DEFAULT_FG}Choose option (1-6, or b): ${NC}")" provider_choice
}

# Function to prompt for Ollama CPU/GPU options
prompt_ollama_options() {
    clear
    echo -e "\n${DEFAULT_FG}${BOLD}Serve Local with Ollama${NC}"
    echo -e "${DEFAULT_FG}Choose how to serve Ollama:${NC}"
    echo -e "${YELLOW}1) CPU${NC}"
    echo -e "${YELLOW}2) GPU${NC}"
    echo -e "${YELLOW}b) Back to Main Menu${NC}"
    echo
    read -p "$(echo -e "${DEFAULT_FG}Choose option (1-2, or b): ${NC}")" ollama_choice
}

# 1) Use DocsGPT Public API Endpoint (simple and free)
use_docs_public_api_endpoint() {
    echo -e "\n${NC}Setting up DocsGPT Public API Endpoint...${NC}"
    echo "LLM_PROVIDER=docsgpt" > .env
    echo "VITE_API_STREAMING=true" >> .env
    echo -e "${GREEN}.env file configured for DocsGPT Public API.${NC}"

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build && docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d
    docker_compose_status=$? # Capture exit status of docker compose

    echo "Docker Compose Exit Status: $docker_compose_status"

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo -e "\n${GREEN}DocsGPT is now running on http://localhost:5173${NC}"
    echo -e "${YELLOW}You can stop the application by running: docker compose -f \"${COMPOSE_FILE}\" down${NC}"
}

# 2) Serve Local (with Ollama)
serve_local_ollama() {
    local ollama_choice model_name
    local docker_compose_file_suffix
    local model_name_prompt
    local default_model="llama3.2:1b"

    get_model_name_ollama() {
        read -p "$(echo -e "${DEFAULT_FG}Enter Ollama Model Name (leave empty for default: ${default_model} (1.3GB)): ${NC}")" model_name_input
        if [ -z "$model_name_input" ]; then
            model_name="$default_model" # Set default model if input is empty
        else
            model_name="$model_name_input" # Use user-provided model name
        fi
    }


    while true; do
        clear
        prompt_ollama_options
        case "$ollama_choice" in
            1) # CPU
                docker_compose_file_suffix="cpu"
                get_model_name_ollama
                break ;;
            2) # GPU
                echo -e "\n${YELLOW}For this option to work correctly you need to have a supported GPU and configure Docker to utilize it.${NC}"
                echo -e "${YELLOW}Refer to: https://hub.docker.com/r/ollama/ollama for more information.${NC}"
                read -p "$(echo -e "${DEFAULT_FG}Continue with GPU setup? (y/b): ${NC}")" confirm_gpu
                case "$confirm_gpu" in
                    y|Y)
                        docker_compose_file_suffix="gpu"
                        get_model_name_ollama
                        break ;;
                    b|B) clear; return ;; # Back to Main Menu
                    *) echo -e "\n${RED}Invalid choice. Please choose y or b.${NC}" ; sleep 1 ;;
                esac
                ;;
            b|B) clear; return ;; # Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-2, or b.${NC}" ; sleep 1 ;;
        esac
    done


    echo -e "\n${NC}Configuring for Ollama ($(echo "$docker_compose_file_suffix" | tr '[:lower:]' '[:upper:]'))...${NC}" # Using tr for uppercase - more compatible
    echo "API_KEY=xxxx" > .env # Placeholder API Key
    echo "LLM_PROVIDER=openai" >> .env
    echo "LLM_NAME=$model_name" >> .env
    echo "VITE_API_STREAMING=true" >> .env
    echo "OPENAI_BASE_URL=http://ollama:11434/v1" >> .env
    echo "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" >> .env
    echo -e "${GREEN}.env file configured for Ollama ($(echo "$docker_compose_file_suffix" | tr '[:lower:]' '[:upper:]')${NC}${GREEN}).${NC}"


    check_and_start_docker
    local compose_files=(
        -f "${COMPOSE_FILE}"
        -f "$(dirname "${COMPOSE_FILE}")/optional/docker-compose.optional.ollama-${docker_compose_file_suffix}.yaml"
    )

    echo -e "\n${NC}Starting Docker Compose with Ollama (${docker_compose_file_suffix})...${NC}"
    docker compose --env-file "${ENV_FILE}" "${compose_files[@]}" build
    docker compose --env-file "${ENV_FILE}" "${compose_files[@]}" up -d
    docker_compose_status=$?

    echo "Docker Compose Exit Status: $docker_compose_status" # Debug output

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo "Waiting for Ollama container to be ready..."
    OLLAMA_READY=false
    while ! $OLLAMA_READY; do
        CONTAINER_STATUS=$(docker compose "${compose_files[@]}" ps --services --filter "status=running" --format '{{.Service}}')
        if [[ "$CONTAINER_STATUS" == *"ollama"* ]]; then # Check if 'ollama' service is in running services
            OLLAMA_READY=true
            echo "Ollama container is running."
        else
            echo "Ollama container not yet ready, waiting..."
            sleep 5
        fi
    done

    echo "Pulling $model_name model for Ollama..."
    docker compose --env-file "${ENV_FILE}" "${compose_files[@]}" exec -it ollama ollama pull "$model_name"


    echo -e "\n${GREEN}DocsGPT is now running with Ollama (${docker_compose_file_suffix}) on http://localhost:5173${NC}"
    printf -v compose_files_escaped "%q " "${compose_files[@]}"
    echo -e "${YELLOW}You can stop the application by running: docker compose ${compose_files_escaped}down${NC}"
}

# 3) Connect Local Inference Engine
connect_local_inference_engine() {
    local engine_choice
    local model_name_prompt model_name openai_base_url

    get_model_name() {
        read -p "$(echo -e "${DEFAULT_FG}Enter Model Name (leave empty to set later as None): ${NC}")" model_name
        if [ -z "$model_name" ]; then
            model_name="None"
        fi
    }

    while true; do
        clear
        prompt_local_inference_engine_options
        case "$engine_choice" in
            1) # LLaMa.cpp
                engine_name="LLaMa.cpp"
                openai_base_url="http://localhost:8000/v1"
                get_model_name
                break ;;
            2) # Ollama
                engine_name="Ollama"
                openai_base_url="http://localhost:11434/v1"
                get_model_name
                break ;;
            3) # TGI
                engine_name="TGI"
                openai_base_url="http://localhost:8080/v1"
                get_model_name
                break ;;
            4) # SGLang
                engine_name="SGLang"
                openai_base_url="http://localhost:30000/v1"
                get_model_name
                break ;;
            5) # vLLM
                engine_name="vLLM"
                openai_base_url="http://localhost:8000/v1"
                get_model_name
                break ;;
            6) # Aphrodite
                engine_name="Aphrodite"
                openai_base_url="http://localhost:2242/v1"
                get_model_name
                break ;;
            7) # FriendliAI
                engine_name="FriendliAI"
                openai_base_url="http://localhost:8997/v1"
                get_model_name
                break ;;
            8) # LMDeploy
                engine_name="LMDeploy"
                openai_base_url="http://localhost:23333/v1"
                get_model_name
                break ;;
            b|B) clear; return ;; # Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-8, or b.${NC}" ; sleep 1 ;;
        esac
    done

    echo -e "\n${NC}Configuring for Local Inference Engine: ${BOLD}${engine_name}...${NC}"
    echo "API_KEY=None" > .env
    echo "LLM_PROVIDER=openai" >> .env
    echo "LLM_NAME=$model_name" >> .env
    echo "VITE_API_STREAMING=true" >> .env
    echo "OPENAI_BASE_URL=$openai_base_url" >> .env
    echo "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" >> .env
    echo -e "${GREEN}.env file configured for ${BOLD}${engine_name}${NC}${GREEN} with OpenAI API format.${NC}"
    echo -e "${YELLOW}Note: MODEL_NAME is set to '${BOLD}$model_name${NC}${YELLOW}'. You can change it later in the .env file.${NC}"

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build && docker compose -f "${COMPOSE_FILE}" up -d
    docker_compose_status=$?

    echo "Docker Compose Exit Status: $docker_compose_status" # Debug output

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo -e "\n${GREEN}DocsGPT is now configured to connect to ${BOLD}${engine_name}${NC}${GREEN} at ${BOLD}$openai_base_url${NC}"
    echo -e "${YELLOW}Ensure your ${BOLD}${engine_name} inference server is running at that address${NC}"
    echo -e "\n${GREEN}DocsGPT is running at http://localhost:5173${NC}"
    echo -e "${YELLOW}You can stop the application by running: docker compose -f \"${COMPOSE_FILE}\" down${NC}"
}


# 4) Connect Cloud API Provider
connect_cloud_api_provider() {
    local provider_choice api_key llm_provider
    local setup_result # Variable to store the return status

    get_api_key() {
        echo -e "${YELLOW}Your API key will be stored locally in the .env file and will not be sent anywhere else${NC}"
        read -p "$(echo -e "${DEFAULT_FG}Please enter your API key: ${NC}")" api_key
    }

    while true; do
        clear
        prompt_cloud_api_provider_options
        case "$provider_choice" in
            1) # OpenAI
                provider_name="OpenAI"
                llm_provider="openai"
                model_name="gpt-4o"
                get_api_key
                break ;;
            2) # Google
                provider_name="Google (Vertex AI, Gemini)"
                llm_provider="google"
                model_name="gemini-2.0-flash"
                get_api_key
                break ;;
            3) # Anthropic
                provider_name="Anthropic (Claude)"
                llm_provider="anthropic"
                model_name="claude-3-5-sonnet-latest"
                get_api_key
                break ;;
            4) # Groq
                provider_name="Groq"
                llm_provider="groq"
                model_name="llama-3.1-8b-instant"
                get_api_key
                break ;;
            5) # HuggingFace Inference API
                provider_name="HuggingFace Inference API"
                llm_provider="huggingface"
                model_name="meta-llama/Llama-3.1-8B-Instruct"
                get_api_key
                break ;;
            6) # Azure OpenAI
                provider_name="Azure OpenAI"
                llm_provider="azure_openai"
                model_name="gpt-4o"
                get_api_key
                break ;;
            7) # Novita
                provider_name="Novita"
                llm_provider="novita"
                model_name="deepseek/deepseek-r1"
                get_api_key
                break ;;
            b|B) clear; return ;; # Clear screen and Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-6, or b.${NC}" ; sleep 1 ;;
        esac
    done

    echo -e "\n${NC}Configuring for Cloud API Provider: ${BOLD}${provider_name}...${NC}"
    echo "API_KEY=$api_key" > .env
    echo "LLM_PROVIDER=$llm_provider" >> .env
    echo "LLM_NAME=$model_name" >> .env
    echo "VITE_API_STREAMING=true" >> .env
    echo -e "${GREEN}.env file configured for ${BOLD}${provider_name}${NC}${GREEN}.${NC}"

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --build
    docker_compose_status=$?

    echo "Docker Compose Exit Status: $docker_compose_status" # Debug output

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo -e "\n${GREEN}DocsGPT is now configured to use ${BOLD}${provider_name}${NC}${GREEN} on http://localhost:5173${NC}"
    echo -e "${YELLOW}You can stop the application by running: docker compose -f \"${COMPOSE_FILE}\" down${NC}"
}


# Main script execution
animate_dino

while true; do # Main menu loop
    clear # Clear screen before showing main menu again
    prompt_main_menu

    case $main_choice in
        1) # Use DocsGPT Public API Endpoint
            use_docs_public_api_endpoint
            break ;;
        2) # Serve Local (with Ollama)
            serve_local_ollama
            break ;;
        3) # Connect Local Inference Engine
            connect_local_inference_engine
            break ;;
        4) # Connect Cloud API Provider
            connect_cloud_api_provider
            break ;;
        *)
            echo -e "\n${RED}Invalid choice. Please choose 1-4.${NC}" ; sleep 1 ;;
    esac
done

echo -e "\n${GREEN}${BOLD}DocsGPT Setup Complete.${NC}"

exit 0