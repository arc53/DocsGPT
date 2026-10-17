#!/bin/bash

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
DEFAULT_FG='\033[39m'
RED='\033[0;31m'
NC='\033[0m'
BOLD='\033[1m'

# Base Compose file (relative to script location)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
COMPOSE_FILE="${SCRIPT_DIR}/deployment/docker-compose-hub.yaml"
COMPOSE_FILE_LOCAL="${SCRIPT_DIR}/deployment/docker-compose.yaml"
ENV_FILE="${SCRIPT_DIR}/.env"

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
    echo -e "${YELLOW}1) Use DocsGPT Public API Endpoint (simple and free, uses pre-built Docker images from Docker Hub for fastest setup)${NC}"
    echo -e "${YELLOW}2) Serve Local (with Ollama)${NC}"
    echo -e "${YELLOW}3) Connect Local Inference Engine${NC}"
    echo -e "${YELLOW}4) Connect Cloud API Provider${NC}"
    echo -e "${YELLOW}5) Advanced: Build images locally (for developers)${NC}"
    echo
    echo -e "${DEFAULT_FG}By default, DocsGPT uses pre-built images from Docker Hub for a fast, reliable, and consistent experience. This avoids local build errors and speeds up onboarding. Advanced users can choose to build images locally if needed.${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-5): ${NC}")" main_choice
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
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-8, or b): ${NC}")" engine_choice
}

# Function to prompt for Cloud API Provider options
prompt_cloud_api_provider_options() {
    clear
    echo -e "\n${DEFAULT_FG}${BOLD}Connect Cloud API Provider${NC}"
    echo -e "${DEFAULT_FG}Choose your Cloud API Provider:${NC}"
    echo -e "${YELLOW}1) OpenAI${NC}"
    echo -e "${YELLOW}2) Google Gemini (AI Studio API key)${NC}"
    echo -e "${YELLOW}3) Anthropic (Claude)${NC}"
    echo -e "${YELLOW}4) Groq${NC}"
    echo -e "${YELLOW}5) Novita${NC}"
    echo -e "${YELLOW}b) Back to Main Menu${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-5, or b): ${NC}")" provider_choice
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
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-2, or b): ${NC}")" ollama_choice
}

# ========================
# .env helpers
# ========================

# .env holds API keys and the JWT, encryption and OIDC secrets, so only its owner may read it.
secure_env_file() {
    (umask 077 && touch "$ENV_FILE") && chmod 600 "$ENV_FILE"
}

# Start a new, empty .env (readable by its owner only), replacing the one there
reset_env_file() {
    secure_env_file && : > "$ENV_FILE"
}

# VALUE as written in .env, so Docker Compose (env_file and --env-file) and python-dotenv (a native
# run) both read it back unchanged. Returns 1 when only Compose will: a value holding a $ together
# with a single quote, ${, or a backslash pair python-dotenv decodes.
format_env_value() {
    local value="$1" plain='^[A-Za-z0-9_./:@+,=-]*$'
    if [[ "$value" =~ $plain ]]; then
        printf '%s' "$value"
    elif [[ "$value" != *"'"* && "$value" != *'${'* && "$value" != *'\\'* && "$value" != *'\' ]]; then
        # Single quotes are literal to Compose; python-dotenv only expands ${...} and decodes \\ and \' in them.
        printf "'%s'" "$value"
    else
        # Double quotes: both decode \\ and \". Compose also interpolates $, which $$ keeps literal, while
        # python-dotenv keeps $$ as it is; a value without a $ reads the same to both.
        value="${value//\\/\\\\}"
        value="${value//\"/\\\"}"
        printf '"%s"' "${value//\$/\$\$}"
        [[ "$value" != *'$'* ]]
    fi
}

# Append KEY=VALUE to .env, quoted as format_env_value does
write_env() {
    local key="$1" formatted
    if ! formatted=$(format_env_value "$2"); then
        echo -e "${YELLOW}${key} is written for Docker Compose; a native (non-Docker) run reads it differently. Edit it in .env if you run DocsGPT natively.${NC}"
    fi
    secure_env_file && printf '%s=%s\n' "$key" "$formatted" >> "$ENV_FILE"
}

# Append KEY=RAW to .env as it stands: RAW is a value read from a .env, already quoted
write_env_raw() {
    secure_env_file && printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
}

# The value of KEY in FILE (default: .env), without the quotes write_env adds; empty when unset
read_env_value() {
    local key="$1" file="${2:-$ENV_FILE}" value
    value=$(grep "^${key}=" "$file" 2>/dev/null | tail -n 1 | cut -d= -f2-)
    if [[ ${#value} -ge 2 && "$value" == \'*\' ]]; then
        value="${value:1:${#value}-2}"
    elif [[ ${#value} -ge 2 && "$value" == \"*\" ]]; then
        value="${value:1:${#value}-2}"
        value="${value//\\\\/$'\001'}"
        value="${value//\\\"/\"}"
        value="${value//\$\$/\$}"
        value="${value//$'\001'/\\}"
    fi
    printf '%s' "$value"
}

# ========================
# Advanced Settings Functions
# ========================

# Vector Store configuration
configure_vector_store() {
    echo -e "\n${DEFAULT_FG}${BOLD}Vector Store Configuration${NC}"
    echo -e "${DEFAULT_FG}Choose your vector store:${NC}"
    echo -e "${YELLOW}1) FAISS (default, local)${NC}"
    echo -e "${YELLOW}2) Elasticsearch${NC}"
    echo -e "${YELLOW}3) Qdrant${NC}"
    echo -e "${YELLOW}4) Milvus${NC}"
    echo -e "${YELLOW}5) PGVector${NC}"
    echo -e "${YELLOW}b) Back${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-5, or b): ${NC}")" vs_choice

    case "$vs_choice" in
        1)
            write_env VECTOR_STORE "faiss"
            echo -e "${GREEN}Vector store set to FAISS.${NC}"
            ;;
        2)
            write_env VECTOR_STORE "elasticsearch"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Elasticsearch URL (e.g. http://localhost:9200): ${NC}")" elastic_url
            [ -n "$elastic_url" ] && write_env ELASTIC_URL "$elastic_url"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Elasticsearch Cloud ID (leave empty if using URL): ${NC}")" elastic_cloud_id
            [ -n "$elastic_cloud_id" ] && write_env ELASTIC_CLOUD_ID "$elastic_cloud_id"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Elasticsearch username (leave empty if none): ${NC}")" elastic_user
            [ -n "$elastic_user" ] && write_env ELASTIC_USERNAME "$elastic_user"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Elasticsearch password (leave empty if none): ${NC}")" elastic_pass
            [ -n "$elastic_pass" ] && write_env ELASTIC_PASSWORD "$elastic_pass"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Elasticsearch index name (default: docsgpt): ${NC}")" elastic_index
            write_env ELASTIC_INDEX "${elastic_index:-docsgpt}"
            echo -e "${GREEN}Vector store set to Elasticsearch.${NC}"
            ;;
        3)
            write_env VECTOR_STORE "qdrant"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Qdrant URL (e.g. http://localhost:6333): ${NC}")" qdrant_url
            [ -n "$qdrant_url" ] && write_env QDRANT_URL "$qdrant_url"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Qdrant API key (leave empty if none): ${NC}")" qdrant_key
            [ -n "$qdrant_key" ] && write_env QDRANT_API_KEY "$qdrant_key"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Qdrant collection name (default: docsgpt): ${NC}")" qdrant_collection
            write_env QDRANT_COLLECTION_NAME "${qdrant_collection:-docsgpt}"
            echo -e "${GREEN}Vector store set to Qdrant.${NC}"
            ;;
        4)
            write_env VECTOR_STORE "milvus"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Milvus URI (default: ./milvus_local.db): ${NC}")" milvus_uri
            write_env MILVUS_URI "${milvus_uri:-./milvus_local.db}"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Milvus token (leave empty if none): ${NC}")" milvus_token
            [ -n "$milvus_token" ] && write_env MILVUS_TOKEN "$milvus_token"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Milvus collection name (default: docsgpt): ${NC}")" milvus_collection
            write_env MILVUS_COLLECTION_NAME "${milvus_collection:-docsgpt}"
            echo -e "${GREEN}Vector store set to Milvus.${NC}"
            ;;
        5)
            write_env VECTOR_STORE "pgvector"
            read -rp "$(echo -e "${DEFAULT_FG}Enter PGVector connection string (e.g. postgresql://user:pass@host:5432/db): ${NC}")" pgvector_conn
            [ -n "$pgvector_conn" ] && write_env PGVECTOR_CONNECTION_STRING "$pgvector_conn"
            echo -e "${GREEN}Vector store set to PGVector.${NC}"
            ;;
        b|B) return ;;
        *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
    esac
}

# Embeddings configuration
configure_embeddings() {
    echo -e "\n${DEFAULT_FG}${BOLD}Embeddings Configuration${NC}"
    echo -e "${DEFAULT_FG}Choose your embeddings provider:${NC}"
    echo -e "${YELLOW}1) Granite multilingual (default, local)${NC}"
    echo -e "${YELLOW}2) OpenAI Embeddings${NC}"
    echo -e "${YELLOW}3) Custom Remote Embeddings (OpenAI-compatible API)${NC}"
    echo -e "${YELLOW}4) all-mpnet-base-v2 (legacy local, English-only)${NC}"
    echo -e "${YELLOW}b) Back${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-4, or b): ${NC}")" emb_choice

    case "$emb_choice" in
        1)
            write_env EMBEDDINGS_NAME "ibm-granite/granite-embedding-311m-multilingual-r2"
            echo -e "${GREEN}Embeddings set to granite-311m-multilingual-r2 (local).${NC}"
            ;;
        2)
            write_env EMBEDDINGS_NAME "openai_text-embedding-ada-002"
            read -rp "$(echo -e "${DEFAULT_FG}Enter OpenAI API key for embeddings (leave empty to reuse API_KEY, only if the LLM provider is OpenAI): ${NC}")" emb_key
            [ -n "$emb_key" ] && write_env EMBEDDINGS_KEY "$emb_key"
            echo -e "${GREEN}Embeddings set to OpenAI.${NC}"
            ;;
        3)
            read -rp "$(echo -e "${DEFAULT_FG}Enter embeddings model name: ${NC}")" emb_name
            [ -n "$emb_name" ] && write_env EMBEDDINGS_NAME "$emb_name"
            read -rp "$(echo -e "${DEFAULT_FG}Enter remote embeddings API base URL: ${NC}")" emb_url
            [ -n "$emb_url" ] && write_env EMBEDDINGS_BASE_URL "$emb_url"
            read -rp "$(echo -e "${DEFAULT_FG}Enter embeddings API key (leave empty if none): ${NC}")" emb_key
            [ -n "$emb_key" ] && write_env EMBEDDINGS_KEY "$emb_key"
            echo -e "${GREEN}Custom remote embeddings configured.${NC}"
            ;;
        4)
            write_env EMBEDDINGS_NAME "huggingface_sentence-transformers/all-mpnet-base-v2"
            echo -e "${GREEN}Embeddings set to all-mpnet-base-v2 (legacy local).${NC}"
            ;;
        b|B) return ;;
        *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
    esac
}

# Authentication configuration
configure_auth() {
    echo -e "\n${DEFAULT_FG}${BOLD}Authentication Configuration${NC}"
    echo -e "${DEFAULT_FG}Choose authentication type:${NC}"
    echo -e "${YELLOW}1) None (default): no sign-in, every visitor shares one account${NC}"
    echo -e "${YELLOW}2) Simple JWT: one shared access token, everyone who has it is the same user${NC}"
    echo -e "${YELLOW}3) Session JWT: keeps browsers apart, but anyone who can reach DocsGPT gets in${NC}"
    echo -e "${YELLOW}4) OIDC: separate accounts, sign-in through your identity provider (Authentik, Keycloak, Okta, ...)${NC}"
    echo -e "${YELLOW}b) Back${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-4, or b): ${NC}")" auth_choice

    case "$auth_choice" in
        1)
            remove_env_keys AUTH_TYPE $OIDC_ENV_KEYS
            echo -e "${GREEN}Authentication disabled (default).${NC}"
            ;;
        2)
            remove_env_keys AUTH_TYPE $OIDC_ENV_KEYS
            write_env AUTH_TYPE "simple_jwt"
            write_jwt_secret_key
            echo -e "${GREEN}Authentication set to Simple JWT.${NC}"
            echo -e "${DEFAULT_FG}The page asks for the access token. The backend prints it when it starts:${NC}"
            echo -e "${DEFAULT_FG}  docker compose --env-file \"${ENV_FILE}\" -f \"${COMPOSE_FILE}\" logs backend | grep \"Simple JWT\"${NC}"
            ;;
        3)
            remove_env_keys AUTH_TYPE $OIDC_ENV_KEYS
            write_env AUTH_TYPE "session_jwt"
            write_jwt_secret_key
            echo -e "${GREEN}Authentication set to Session JWT.${NC}"
            ;;
        4) configure_oidc ;;
        b|B) return ;;
        *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
    esac
}

# The OIDC settings configure_oidc writes; choosing another mode removes them
OIDC_ENV_KEYS="OIDC_ISSUER OIDC_CLIENT_ID OIDC_CLIENT_SECRET OIDC_FRONTEND_URL OIDC_ADMIN_GROUPS"

# Ask until the answer is not empty; fails when input ends first (callers exit on that)
read_required() {
    local prompt="$1" answer=""
    while [ -z "$answer" ]; do
        if ! read -rp "$(echo -e "${DEFAULT_FG}${prompt}: ${NC}")" answer; then
            echo -e "\n${RED}No answer for \"${prompt}\": input ended. Setup stopped.${NC}" >&2
            return 1
        fi
    done
    echo "$answer"
}

# AUTH_TYPE=oidc: sign-in through an OpenID Connect identity provider
configure_oidc() {
    local issuer client_id client_secret frontend_url default_frontend admin_groups api_origin
    echo -e "\n${DEFAULT_FG}Register DocsGPT as an OAuth2/OpenID client (authorization code flow) at your identity provider${NC}"
    echo -e "${DEFAULT_FG}first. Guide: https://docs.docsgpt.cloud/Deploying/OIDC-SSO${NC}"
    issuer=$(read_required "Issuer URL (e.g. https://auth.example.com/application/o/docsgpt/)") || exit 1
    client_id=$(read_required "Client ID") || exit 1
    read -rp "$(echo -e "${DEFAULT_FG}Client secret (leave empty for a public client; PKCE is always used): ${NC}")" client_secret
    if grep -q "^API_URL=" "$ENV_FILE" 2>/dev/null; then
        default_frontend=$(read_env_value API_URL)
        read -rp "$(echo -e "${DEFAULT_FG}Address people open DocsGPT at (leave empty for ${default_frontend}): ${NC}")" frontend_url
        frontend_url="${frontend_url:-$default_frontend}"
    elif grep -q "^DOCSGPT_BIND=0.0.0.0" "$ENV_FILE" 2>/dev/null; then
        frontend_url=$(read_required "Address people open DocsGPT at (e.g. https://docs.example.com or http://192.168.1.10:7091)") || exit 1
    else
        default_frontend="http://localhost:5173"
        read -rp "$(echo -e "${DEFAULT_FG}Address people open DocsGPT at (leave empty for ${default_frontend}): ${NC}")" frontend_url
        frontend_url="${frontend_url:-$default_frontend}"
    fi
    frontend_url="${frontend_url%/}"
    read -rp "$(echo -e "${DEFAULT_FG}IdP groups whose members become DocsGPT admins, comma-separated (leave empty for none): ${NC}")" admin_groups

    remove_env_keys AUTH_TYPE $OIDC_ENV_KEYS
    write_env AUTH_TYPE "oidc"
    write_env OIDC_ISSUER "$issuer"
    write_env OIDC_CLIENT_ID "$client_id"
    [ -n "$client_secret" ] && write_env OIDC_CLIENT_SECRET "$client_secret"
    write_env OIDC_FRONTEND_URL "$frontend_url"
    [ -n "$admin_groups" ] && write_env OIDC_ADMIN_GROUPS "$admin_groups"
    ensure_jwt_secret_key

    # The UI on 5173 calls the API on 7091; the backend image serves the UI on its own port.
    if [ "$frontend_url" = "http://localhost:5173" ]; then
        api_origin="http://localhost:7091"
    else
        api_origin="$frontend_url"
    fi
    echo -e "${GREEN}Authentication set to OIDC.${NC}"
    echo -e "${DEFAULT_FG}Register this redirect URI at your identity provider:${NC}"
    echo -e "${DEFAULT_FG}  ${api_origin}/api/auth/oidc/callback${NC}"
    echo -e "${DEFAULT_FG}Behind a reverse proxy, set OIDC_REDIRECT_URI in .env to the public callback URL instead.${NC}"
    if [ -z "$admin_groups" ]; then
        echo -e "${YELLOW}No admin groups set: nobody is an admin until you grant the first one. See${NC}"
        echo -e "${YELLOW}https://docs.docsgpt.cloud/Deploying/Access-Control#bootstrapping-the-first-admin${NC}"
    fi
}

# Ask for a JWT signing key; empty keeps the one already in .env (generated, or carried over)
write_jwt_secret_key() {
    local jwt_key
    read -rp "$(echo -e "${DEFAULT_FG}Enter JWT secret key (leave empty to keep the one in .env): ${NC}")" jwt_key
    if [ -n "$jwt_key" ]; then
        remove_env_keys JWT_SECRET_KEY
        write_env JWT_SECRET_KEY "$jwt_key"
    fi
    ensure_jwt_secret_key
}

# Drop settings from .env so choosing again does not leave the earlier value behind
remove_env_keys() {
    local key
    [ -f "$ENV_FILE" ] || return 0
    for key in "$@"; do
        # The copy is created owner-only, so the .env it replaces stays that way.
        (umask 077 && grep -v "^${key}=" "$ENV_FILE" > "${ENV_FILE}.tmp")
        mv "${ENV_FILE}.tmp" "$ENV_FILE"
    done
}

# Integrations configuration
configure_integrations() {
    echo -e "\n${DEFAULT_FG}${BOLD}Integrations Configuration${NC}"
    echo -e "${YELLOW}1) Google Drive${NC}"
    echo -e "${YELLOW}2) GitHub${NC}"
    echo -e "${YELLOW}b) Back${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-2, or b): ${NC}")" int_choice

    case "$int_choice" in
        1)
            read -rp "$(echo -e "${DEFAULT_FG}Enter Google OAuth Client ID: ${NC}")" google_id
            [ -n "$google_id" ] && write_env GOOGLE_CLIENT_ID "$google_id"
            read -rp "$(echo -e "${DEFAULT_FG}Enter Google OAuth Client Secret: ${NC}")" google_secret
            [ -n "$google_secret" ] && write_env GOOGLE_CLIENT_SECRET "$google_secret"
            echo -e "${GREEN}Google Drive integration configured.${NC}"
            ;;
        2)
            read -rp "$(echo -e "${DEFAULT_FG}Enter GitHub Personal Access Token (with repo read access): ${NC}")" github_token
            [ -n "$github_token" ] && write_env GITHUB_ACCESS_TOKEN "$github_token"
            echo -e "${GREEN}GitHub integration configured.${NC}"
            ;;
        b|B) return ;;
        *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
    esac
}

# Document Processing configuration
configure_doc_processing() {
    echo -e "\n${DEFAULT_FG}${BOLD}Document Processing Configuration${NC}"
    read -rp "$(echo -e "${DEFAULT_FG}Parse PDF pages as images for better table/chart extraction? (y/N): ${NC}")" pdf_image
    if [[ "$pdf_image" =~ ^[yY]$ ]]; then
        write_env PARSE_PDF_AS_IMAGE "true"
        echo -e "${GREEN}PDF-as-image parsing enabled.${NC}"
    fi

    # OCR needs the tesseract binary. The default (slim) images ship without
    # it; the pre-built "-docling" image variant bakes tesseract, the docling
    # layout engine and its models in, so with Docker Hub images OCR means
    # switching the variant. Locally built images get it via build args.
    read -rp "$(echo -e "${DEFAULT_FG}Enable OCR for scanned PDFs and images? (y/N): ${NC}")" ocr_enabled
    if [[ ! "$ocr_enabled" =~ ^[yY]$ ]]; then
        return
    fi
    write_env OCR_ENABLED "true"
    if [[ "$COMPOSE_FILE" != "$COMPOSE_FILE_LOCAL" ]]; then
        # Pre-built images: pull arc53/docsgpt:<tag>-docling instead of the
        # slim default (about 1.5 GB more to download).
        write_env DOCSGPT_IMAGE_VARIANT "-docling"
        echo -e "${GREEN}OCR enabled. The -docling image variant will be pulled (tesseract, docling layout engine and its models included). For a DeepSeek-OCR endpoint instead, set OCR_ENGINE=deepseek in .env (local Ollama by default; OCR_DEEPSEEK_PROVIDER=novita or deepinfra plus OCR_DEEPSEEK_API_KEY for a hosted API).${NC}"
        return
    fi
    # Bakes tesseract into the locally built images (docker compose
    # --env-file .env build).
    write_env INSTALL_TESSERACT "true"
    echo -e "${GREEN}OCR enabled. tesseract will be built into the images (INSTALL_TESSERACT=true); for a DeepSeek-OCR endpoint instead, set OCR_ENGINE=deepseek in .env (local Ollama by default; OCR_DEEPSEEK_PROVIDER=novita or deepinfra plus OCR_DEEPSEEK_API_KEY for a hosted API).${NC}"
    read -rp "$(echo -e "${DEFAULT_FG}Also install the Docling layout engine for OCR (better tables/reading order, several GB heavier)? (y/N): ${NC}")" docling_ocr
    if [[ "$docling_ocr" =~ ^[yY]$ ]]; then
        # Locally built images include docling via this build arg; it becomes
        # the OCR backend automatically (OCR_BACKEND=auto).
        write_env INSTALL_DOCLING "true"
        echo -e "${GREEN}Docling will be built into locally built images (docker compose --env-file .env build).${NC}"
    fi
}

# Text-to-Speech configuration
configure_tts() {
    echo -e "\n${DEFAULT_FG}${BOLD}Text-to-Speech Configuration${NC}"
    echo -e "${DEFAULT_FG}Choose TTS provider:${NC}"
    echo -e "${YELLOW}1) Google TTS (default, free)${NC}"
    echo -e "${YELLOW}2) ElevenLabs${NC}"
    echo -e "${YELLOW}b) Back${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-2, or b): ${NC}")" tts_choice

    case "$tts_choice" in
        1)
            write_env TTS_PROVIDER "google_tts"
            echo -e "${GREEN}TTS set to Google TTS.${NC}"
            ;;
        2)
            write_env TTS_PROVIDER "elevenlabs"
            read -rp "$(echo -e "${DEFAULT_FG}Enter ElevenLabs API key: ${NC}")" elevenlabs_key
            [ -n "$elevenlabs_key" ] && write_env ELEVENLABS_API_KEY "$elevenlabs_key"
            echo -e "${GREEN}TTS set to ElevenLabs.${NC}"
            ;;
        b|B) return ;;
        *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
    esac
}

# Generate INTERNAL_KEY for worker-to-backend auth if not already present
# (a rerun carries over the one in the .env it overwrites, so the worker keeps working)
ensure_internal_key() {
    if ! grep -q "^INTERNAL_KEY=" "$ENV_FILE" 2>/dev/null; then
        local internal_key="$PREVIOUS_INTERNAL_KEY"
        if [ -z "$internal_key" ]; then
            internal_key=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')
        fi
        write_env_raw INTERNAL_KEY "$internal_key"
    fi
}

# Generate JWT_SECRET_KEY, shared by the backend and worker containers, if not already present.
# A rerun carries over the one in the .env it overwrites: a new key would sign everyone out and,
# under session_jwt, leave their data behind.
ensure_jwt_secret_key() {
    if ! grep -q "^JWT_SECRET_KEY=" "$ENV_FILE" 2>/dev/null; then
        local jwt_key="$PREVIOUS_JWT_SECRET_KEY"
        if [ -z "$jwt_key" ]; then
            jwt_key=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')
        fi
        write_env_raw JWT_SECRET_KEY "$jwt_key"
    fi
}

# Generate ENCRYPTION_SECRET_KEY, which seals stored connector, MCP and tool credentials. A key
# is never replaced: credentials already stored are sealed with it. A rerun carries it over from
# the .env it overwrites (with ENCRYPTION_SECRET_KEY_PREVIOUS, while a rotation is unfinished), and
# an install whose .env had none keeps the default rather than lose the credentials it may already
# hold under it. A new key keeps the default as the previous one: a Docker volume kept from an
# earlier install may hold credentials sealed with it.
ensure_encryption_key() {
    local encryption_key
    if [ -n "$PREVIOUS_ENCRYPTION_KEY_PREVIOUS" ] && ! grep -q "^ENCRYPTION_SECRET_KEY_PREVIOUS=" "$ENV_FILE" 2>/dev/null; then
        write_env_raw ENCRYPTION_SECRET_KEY_PREVIOUS "$PREVIOUS_ENCRYPTION_KEY_PREVIOUS"
    fi
    if grep -q "^ENCRYPTION_SECRET_KEY=" "$ENV_FILE" 2>/dev/null; then
        return
    fi
    if [ -n "$PREVIOUS_ENCRYPTION_KEY" ]; then
        write_env_raw ENCRYPTION_SECRET_KEY "$PREVIOUS_ENCRYPTION_KEY"
    elif [ "$HAD_ENV_FILE" -eq 1 ]; then
        echo -e "${YELLOW}ENCRYPTION_SECRET_KEY was not generated: this install may already hold credentials sealed with${NC}"
        echo -e "${YELLOW}the default key. To set one, see https://docs.docsgpt.cloud/Deploying/Security#secrets${NC}"
    else
        encryption_key=$(openssl rand -hex 32 2>/dev/null || head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n')
        write_env_raw ENCRYPTION_SECRET_KEY "$encryption_key"
        if ! grep -q "^ENCRYPTION_SECRET_KEY_PREVIOUS=" "$ENV_FILE" 2>/dev/null; then
            write_env_raw ENCRYPTION_SECRET_KEY_PREVIOUS "default-docsgpt-encryption-key"
        fi
        echo -e "${DEFAULT_FG}Generated ENCRYPTION_SECRET_KEY. ENCRYPTION_SECRET_KEY_PREVIOUS keeps credentials a Docker volume from an${NC}"
        echo -e "${DEFAULT_FG}earlier install stored under the public default readable. Once DocsGPT is running, reseal them with${NC}"
        echo -e "${DEFAULT_FG}  docker compose --env-file \"${ENV_FILE}\" -f \"${COMPOSE_FILE}\" exec backend python -m docsgpt connectors reencrypt${NC}"
        echo -e "${DEFAULT_FG}then remove ENCRYPTION_SECRET_KEY_PREVIOUS from .env once it reports nothing unreadable.${NC}"
    fi
}

# This machine's address on its network (the one a default route leaves from), or "localhost"
detect_lan_ip() {
    local ip=""
    if command -v ip >/dev/null 2>&1; then
        ip=$(ip route get 192.0.2.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}')
    fi
    if [ -z "$ip" ] && command -v ipconfig >/dev/null 2>&1; then
        ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
    fi
    if [ -z "$ip" ] && command -v hostname >/dev/null 2>&1; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    echo "${ip:-localhost}"
}

# Ask whether other machines may reach DocsGPT; by default its ports are bound to 127.0.0.1
configure_network_access() {
    local expose_network auth_now default_api_url api_url
    echo
    echo -e "${DEFAULT_FG}DocsGPT is reachable from this computer only (its ports are bound to 127.0.0.1).${NC}"
    read -rp "$(echo -e "${DEFAULT_FG}Make it reachable from other machines on your network? (y/N): ${NC}")" expose_network
    if [[ ! "$expose_network" =~ ^[yY]$ ]]; then
        return
    fi
    write_env DOCSGPT_BIND "0.0.0.0"
    # The backend builds agent image, webhook, device pairing and MCP OAuth callback URLs from API_URL,
    # which otherwise points at localhost. The worker keeps http://backend:7091 from the compose file.
    default_api_url="${PREVIOUS_API_URL:-http://$(detect_lan_ip):7091}"
    read -rp "$(echo -e "${DEFAULT_FG}Address other machines open DocsGPT at (leave empty for ${default_api_url}): ${NC}")" api_url
    api_url="${api_url:-$default_api_url}"
    api_url="${api_url%/}"
    write_env API_URL "$api_url"
    echo -e "\n${YELLOW}${BOLD}Warning:${NC}${YELLOW} anyone who can reach this machine can use DocsGPT and your model API key.${NC}"
    echo -e "${YELLOW}Without authentication there is no sign-in: every visitor shares one account, with its documents,${NC}"
    echo -e "${YELLOW}agents and connected services. Traffic is plain HTTP, so put a TLS proxy in front of it outside a${NC}"
    echo -e "${YELLOW}trusted network. Checklist: https://docs.docsgpt.cloud/Deploying/Security${NC}"
    echo -e "${DEFAULT_FG}From other machines, open ${api_url} (the UI on 5173 calls the API on localhost).${NC}"
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Set up authentication now? (Y/n): ${NC}")" auth_now
    if [[ "$auth_now" =~ ^[nN]$ ]]; then
        echo -e "${YELLOW}No authentication set. Set AUTH_TYPE in .env before anyone else can reach this machine.${NC}"
        return
    fi
    configure_auth
    if ! grep -q "^AUTH_TYPE=" "$ENV_FILE" 2>/dev/null; then
        echo -e "${YELLOW}No authentication set. Set AUTH_TYPE in .env before anyone else can reach this machine.${NC}"
    fi
}

# Main advanced settings menu
prompt_advanced_settings() {
    ensure_internal_key
    ensure_jwt_secret_key
    ensure_encryption_key
    configure_network_access
    echo
    read -rp "$(echo -e "${DEFAULT_FG}Would you like to configure advanced settings? (y/N): ${NC}")" configure_advanced
    if [[ ! "$configure_advanced" =~ ^[yY]$ ]]; then
        return
    fi

    while true; do
        echo -e "\n${DEFAULT_FG}${BOLD}Advanced Settings${NC}"
        echo -e "${YELLOW}1) Vector Store         ${NC}${DEFAULT_FG}(default: faiss)${NC}"
        echo -e "${YELLOW}2) Embeddings           ${NC}${DEFAULT_FG}(default: HuggingFace local)${NC}"
        echo -e "${YELLOW}3) Authentication       ${NC}${DEFAULT_FG}(default: none)${NC}"
        echo -e "${YELLOW}4) Integrations         ${NC}${DEFAULT_FG}(Google Drive, GitHub)${NC}"
        echo -e "${YELLOW}5) Document Processing  ${NC}${DEFAULT_FG}(PDF as image, OCR)${NC}"
        echo -e "${YELLOW}6) Text-to-Speech       ${NC}${DEFAULT_FG}(default: Google TTS)${NC}"
        echo -e "${YELLOW}s) Save and Continue with Docker setup${NC}"
        echo
        read -rp "$(echo -e "${DEFAULT_FG}Choose option (1-6, or s): ${NC}")" adv_choice

        case "$adv_choice" in
            1) configure_vector_store ;;
            2) configure_embeddings ;;
            3) configure_auth ;;
            4) configure_integrations ;;
            5) configure_doc_processing ;;
            6) configure_tts ;;
            s|S) break ;;
            *) echo -e "\n${RED}Invalid choice.${NC}" ; sleep 1 ;;
        esac
    done
}

# 1) Use DocsGPT Public API Endpoint (simple and free)
use_docs_public_api_endpoint() {
    echo -e "\n${NC}Setting up DocsGPT Public API Endpoint...${NC}"
    reset_env_file
    write_env LLM_PROVIDER "docsgpt"
    write_env VITE_API_STREAMING "true"
    echo -e "${GREEN}.env file configured for DocsGPT Public API.${NC}"

    prompt_advanced_settings

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    # Locally built images must be rebuilt rather than reused: INSTALL_TESSERACT
    # and INSTALL_DOCLING are build args, so a rerun that switches OCR on would
    # otherwise keep the image that was built without them.
    up_args=(up -d)
    if [ "$COMPOSE_FILE" = "$COMPOSE_FILE_LOCAL" ]; then
        up_args=(up --build -d)
    fi
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull && docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "${up_args[@]}"
    docker_compose_status=$? # Capture exit status of docker compose

    echo "Docker Compose Exit Status: $docker_compose_status"

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo -e "\n${GREEN}DocsGPT is now running on http://localhost:5173${NC}"
    echo -e "${YELLOW}You can stop the application by running: docker compose --env-file \"${ENV_FILE}\" -f \"${COMPOSE_FILE}\" down${NC}"
}

# 2) Serve Local (with Ollama)
serve_local_ollama() {
    local ollama_choice model_name
    local docker_compose_file_suffix
    local model_name_prompt
    local default_model="llama3.2:1b"

    get_model_name_ollama() {
        read -rp "$(echo -e "${DEFAULT_FG}Enter Ollama Model Name (leave empty for default: ${default_model} (1.3GB)): ${NC}")" model_name_input
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
                read -rp "$(echo -e "${DEFAULT_FG}Continue with GPU setup? (y/b): ${NC}")" confirm_gpu
                case "$confirm_gpu" in
                    y|Y)
                        docker_compose_file_suffix="gpu"
                        get_model_name_ollama
                        break ;;
                    b|B) clear; return 1 ;; # Back to Main Menu
                    *) echo -e "\n${RED}Invalid choice. Please choose y or b.${NC}" ; sleep 1 ;;
                esac
                ;;
            b|B) clear; return 1 ;; # Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-2, or b.${NC}" ; sleep 1 ;;
        esac
    done


    echo -e "\n${NC}Configuring for Ollama ($(echo "$docker_compose_file_suffix" | tr '[:lower:]' '[:upper:]'))...${NC}" # Using tr for uppercase - more compatible
    reset_env_file
    write_env API_KEY "xxxx"
    write_env LLM_PROVIDER "openai"
    write_env LLM_NAME "$model_name"
    write_env VITE_API_STREAMING "true"
    write_env OPENAI_BASE_URL "http://ollama:11434/v1"
    write_env EMBEDDINGS_NAME "ibm-granite/granite-embedding-311m-multilingual-r2"
    echo -e "${GREEN}.env file configured for Ollama ($(echo "$docker_compose_file_suffix" | tr '[:lower:]' '[:upper:]')${NC}${GREEN}).${NC}"

    prompt_advanced_settings

    check_and_start_docker
    local compose_files=(
        -f "${COMPOSE_FILE}"
        -f "$(dirname "${COMPOSE_FILE}")/optional/docker-compose.optional.ollama-${docker_compose_file_suffix}.yaml"
    )

    echo -e "\n${NC}Starting Docker Compose with Ollama (${docker_compose_file_suffix})...${NC}"
    docker compose --env-file "${ENV_FILE}" "${compose_files[@]}" pull
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
        CONTAINER_STATUS=$(docker compose --env-file "${ENV_FILE}" "${compose_files[@]}" ps --services --filter "status=running" --format '{{.Service}}')
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
    echo -e "${YELLOW}You can stop the application by running: docker compose --env-file \"${ENV_FILE}\" ${compose_files_escaped}down${NC}"
}

# 3) Connect Local Inference Engine
connect_local_inference_engine() {
    local engine_choice
    local model_name_prompt model_name openai_base_url

    # DocsGPT registers no model for the server without a name, so one is required. Use the name the
    # server serves (for Ollama, e.g. llama3.2:1b); separate several with commas.
    get_model_name() {
        model_name=""
        while [ -z "$model_name" ]; do
            read -rp "$(echo -e "${DEFAULT_FG}Enter Model Name as your server names it (required; comma-separate several): ${NC}")" model_name
            if [ -z "${model_name//[[:space:]]/}" ]; then
                model_name=""
                echo -e "${RED}A model name is required.${NC}"
            fi
        done
    }

    while true; do
        clear
        prompt_local_inference_engine_options
        case "$engine_choice" in
            1) # LLaMa.cpp
                engine_name="LLaMa.cpp"
                openai_base_url="http://host.docker.internal:8000/v1"
                get_model_name
                break ;;
            2) # Ollama
                engine_name="Ollama"
                openai_base_url="http://host.docker.internal:11434/v1"
                get_model_name
                break ;;
            3) # TGI
                engine_name="TGI"
                openai_base_url="http://host.docker.internal:8080/v1"
                get_model_name
                break ;;
            4) # SGLang
                engine_name="SGLang"
                openai_base_url="http://host.docker.internal:30000/v1"
                get_model_name
                break ;;
            5) # vLLM
                engine_name="vLLM"
                openai_base_url="http://host.docker.internal:8000/v1"
                get_model_name
                break ;;
            6) # Aphrodite
                engine_name="Aphrodite"
                openai_base_url="http://host.docker.internal:2242/v1"
                get_model_name
                break ;;
            7) # FriendliAI
                engine_name="FriendliAI"
                openai_base_url="http://host.docker.internal:8997/v1"
                get_model_name
                break ;;
            8) # LMDeploy
                engine_name="LMDeploy"
                openai_base_url="http://host.docker.internal:23333/v1"
                get_model_name
                break ;;
            b|B) clear; return 1 ;; # Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-8, or b.${NC}" ; sleep 1 ;;
        esac
    done

    echo -e "\n${NC}Configuring for Local Inference Engine: ${BOLD}${engine_name}...${NC}"
    reset_env_file
    write_env API_KEY "None"
    write_env LLM_PROVIDER "openai"
    write_env LLM_NAME "$model_name"
    write_env VITE_API_STREAMING "true"
    write_env OPENAI_BASE_URL "$openai_base_url"
    write_env EMBEDDINGS_NAME "ibm-granite/granite-embedding-311m-multilingual-r2"
    echo -e "${GREEN}.env file configured for ${BOLD}${engine_name}${NC}${GREEN} with OpenAI API format.${NC}"
    echo -e "${YELLOW}Note: MODEL_NAME is set to '${BOLD}$model_name${NC}${YELLOW}'. You can change it later in the .env file.${NC}"

    prompt_advanced_settings

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull && docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d
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
    echo -e "${YELLOW}You can stop the application by running: docker compose --env-file \"${ENV_FILE}\" -f \"${COMPOSE_FILE}\" down${NC}"
}


# 4) Connect Cloud API Provider
connect_cloud_api_provider() {
    local provider_choice api_key llm_provider
    local setup_result # Variable to store the return status

    get_api_key() {
        echo -e "${YELLOW}Your API key will be stored locally in the .env file and will not be sent anywhere else${NC}"
        read -rp "$(echo -e "${DEFAULT_FG}Please enter your API key: ${NC}")" api_key
    }

    while true; do
        clear
        prompt_cloud_api_provider_options
        case "$provider_choice" in
            1) # OpenAI
                provider_name="OpenAI"
                llm_provider="openai"
                model_name="gpt-5.5"
                get_api_key
                break ;;
            2) # Google
                provider_name="Google Gemini (AI Studio API key)"
                llm_provider="google"
                model_name="gemini-3.5-flash"
                get_api_key
                break ;;
            3) # Anthropic
                provider_name="Anthropic (Claude)"
                llm_provider="anthropic"
                model_name="claude-sonnet-4-6"
                get_api_key
                break ;;
            4) # Groq
                provider_name="Groq"
                llm_provider="groq"
                model_name="llama-3.1-8b-instant"
                get_api_key
                break ;;
            5) # Novita
                provider_name="Novita"
                llm_provider="novita"
                model_name="moonshotai/kimi-k2.6"
                get_api_key
                break ;;
            b|B) clear; return 1 ;; # Clear screen and Back to Main Menu
            *) echo -e "\n${RED}Invalid choice. Please choose 1-5, or b.${NC}" ; sleep 1 ;;
        esac
    done

    echo -e "\n${NC}Configuring for Cloud API Provider: ${BOLD}${provider_name}...${NC}"
    reset_env_file
    write_env API_KEY "$api_key"
    write_env LLM_PROVIDER "$llm_provider"
    write_env LLM_NAME "$model_name"
    write_env VITE_API_STREAMING "true"

    echo -e "${GREEN}.env file configured for ${BOLD}${provider_name}${NC}${GREEN}.${NC}"

    prompt_advanced_settings

    check_and_start_docker

    echo -e "\n${NC}Starting Docker Compose...${NC}"
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" pull && docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d
    docker_compose_status=$?

    echo "Docker Compose Exit Status: $docker_compose_status" # Debug output

    if [ "$docker_compose_status" -ne 0 ]; then
        echo -e "\n${RED}${BOLD}Error starting Docker Compose. Please ensure Docker Compose is installed and in your PATH.${NC}"
        echo -e "${RED}Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/${NC}"
        exit 1 # Indicate failure and EXIT SCRIPT
    fi

    echo -e "\n${GREEN}DocsGPT is now configured to use ${BOLD}${provider_name}${NC}${GREEN} on http://localhost:5173${NC}"
    echo -e "${YELLOW}You can stop the application by running: docker compose --env-file \"${ENV_FILE}\" -f \"${COMPOSE_FILE}\" down${NC}"
}


# Main script execution
animate_dino

# Check if .env file exists and is not empty
PREVIOUS_ENCRYPTION_KEY=""
PREVIOUS_ENCRYPTION_KEY_PREVIOUS=""
PREVIOUS_JWT_SECRET_KEY=""
PREVIOUS_INTERNAL_KEY=""
PREVIOUS_API_URL=""
HAD_ENV_FILE=0
if [ -f "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
    HAD_ENV_FILE=1
    # Carried into the new .env: stored credentials are sealed with the encryption key, tokens
    # are signed with the JWT key, and a running worker holds the internal key.
    PREVIOUS_ENCRYPTION_KEY=$(grep "^ENCRYPTION_SECRET_KEY=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
    PREVIOUS_ENCRYPTION_KEY_PREVIOUS=$(grep "^ENCRYPTION_SECRET_KEY_PREVIOUS=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
    PREVIOUS_JWT_SECRET_KEY=$(grep "^JWT_SECRET_KEY=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
    PREVIOUS_INTERNAL_KEY=$(grep "^INTERNAL_KEY=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-)
    # Offered again as the public address if DocsGPT is exposed on this run too.
    PREVIOUS_API_URL=$(read_env_value API_URL)
    echo -e "\n${YELLOW}${BOLD}Warning:${NC}${YELLOW} An existing .env file was found with the following settings:${NC}"
    head -3 "$ENV_FILE" | while IFS= read -r line; do echo -e "${DEFAULT_FG}  $line${NC}"; done
    total_lines=$(wc -l < "$ENV_FILE")
    if [ "$total_lines" -gt 3 ]; then
        echo -e "${DEFAULT_FG}  ... and $((total_lines - 3)) more lines${NC}"
    fi
    echo
    echo -e "${DEFAULT_FG}Its INTERNAL_KEY, JWT_SECRET_KEY and ENCRYPTION_SECRET_KEY (with any ENCRYPTION_SECRET_KEY_PREVIOUS) are kept.${NC}"
    read -rp "$(echo -e "${YELLOW}Running setup will overwrite this file. Continue? (y/N): ${NC}")" confirm_overwrite
    if [[ ! "$confirm_overwrite" =~ ^[yY]$ ]]; then
        echo -e "${GREEN}Setup cancelled. Your .env file was not modified.${NC}"
        exit 0
    fi
fi

while true; do # Main menu loop
    clear # Clear screen before showing main menu again
    prompt_main_menu

    case $main_choice in
        1) # Use DocsGPT Public API Endpoint (Docker Hub images)
            COMPOSE_FILE="${SCRIPT_DIR}/deployment/docker-compose-hub.yaml"
            use_docs_public_api_endpoint
            break ;;
        2) # Serve Local (with Ollama)
            serve_local_ollama && break ;;
        3) # Connect Local Inference Engine
            connect_local_inference_engine && break ;;
        4) # Connect Cloud API Provider
            connect_cloud_api_provider && break ;;
        5) # Advanced: Build images locally
            echo -e "\n${YELLOW}You have selected to build images locally. This is recommended for developers or if you want to test local changes.${NC}"
            COMPOSE_FILE="$COMPOSE_FILE_LOCAL"
            use_docs_public_api_endpoint
            break ;;
        *)
            echo -e "\n${RED}Invalid choice. Please choose 1-5.${NC}" ; sleep 1 ;;
    esac
done

echo -e "\n${GREEN}${BOLD}DocsGPT Setup Complete.${NC}"

exit 0