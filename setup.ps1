# DocsGPT Setup PowerShell Script for Windows
# PowerShell -ExecutionPolicy Bypass -File .\setup.ps1

# Script execution policy - uncomment if needed
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Set error action preference
$ErrorActionPreference = "Stop"

# Get current script directory
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$COMPOSE_FILE_HUB = Join-Path -Path $SCRIPT_DIR -ChildPath "deployment\docker-compose-hub.yaml"
$COMPOSE_FILE_LOCAL = Join-Path -Path $SCRIPT_DIR -ChildPath "deployment\docker-compose.yaml"
$COMPOSE_FILE = $COMPOSE_FILE_HUB
$ENV_FILE = Join-Path -Path $SCRIPT_DIR -ChildPath ".env"

# Function to write colored text
function Write-ColorText {
    param (
        [Parameter(Mandatory=$true)][string]$Text,
        [Parameter()][string]$ForegroundColor = "White",
        [Parameter()][switch]$Bold
    )

    $params = @{
        ForegroundColor = $ForegroundColor
        NoNewline = $false
    }

    if ($Bold) {
        # PowerShell doesn't have bold
        Write-Host $Text @params
    } else {
        Write-Host $Text @params
    }
}

# Animation function (Windows PowerShell version of animate_dino)
function Animate-Dino {
    [Console]::CursorVisible = $false

    # Clear screen
    Clear-Host

    # Static DocsGPT text
    $static_text = @(
        "  ____                  ____ ____ _____ "
        " |  _ \  ___   ___ ___ / ___|  _ \_   _|"
        " | | | |/ _ \ / __/ __| |  _| |_) || |  "
        " | |_| | (_) | (__\__ \ |_| |  __/ | |  "
        " |____/ \___/ \___|___/\____|_|    |_|  "
        "                                        "
    )

    # Print static text
    foreach ($line in $static_text) {
        Write-Host $line
    }

    # Dino ASCII art
    $dino_lines = @(
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

    # Save cursor position
    $cursorPos = $Host.UI.RawUI.CursorPosition

    # Build-up animation
    for ($i = 0; $i -lt $dino_lines.Count; $i++) {
        # Restore cursor position
        $Host.UI.RawUI.CursorPosition = $cursorPos
        
        # Display lines up to current index
        for ($j = 0; $j -le $i; $j++) {
            Write-Host $dino_lines[$j]
        }
        
        # Slow down animation
        Start-Sleep -Milliseconds 50
    }

    # Pause at end of animation
    Start-Sleep -Milliseconds 500

    # Clear the animation
    $Host.UI.RawUI.CursorPosition = $cursorPos
    
    # Clear from cursor to end of screen
    for ($i = 0; $i -lt $dino_lines.Count; $i++) {
        Write-Host (" " * $dino_lines[0].Length)
    }
    
    # Restore cursor position for next output
    $Host.UI.RawUI.CursorPosition = $cursorPos
    
    # Show cursor again
    [Console]::CursorVisible = $true
}

# Check and start Docker function
function Check-AndStartDocker {
    # Check if Docker is running
    try {
        $dockerRunning = $false
        
        # First try with 'docker info' which should work if Docker is fully operational
        try {
            $dockerInfo = docker info 2>&1
            # If we get here without an exception, Docker is running
            Write-ColorText "Docker is already running." -ForegroundColor "Green"
            return $true
        } catch {
            # Docker info command failed
        }
        
        # Check if Docker process is running
        $dockerProcess = Get-Process "Docker Desktop" -ErrorAction SilentlyContinue
        if ($dockerProcess) {
            # Docker Desktop is running, but might not be fully initialized
            Write-ColorText "Docker Desktop is starting up. Waiting for it to be ready..." -ForegroundColor "Yellow"
            
            # Wait for Docker to become operational
            $attempts = 0
            $maxAttempts = 30
            
            while ($attempts -lt $maxAttempts) {
                try {
                    $null = docker ps 2>&1
                    Write-ColorText "Docker is now operational." -ForegroundColor "Green"
                    return $true
                } catch {
                    Write-Host "." -NoNewline
                    Start-Sleep -Seconds 2
                    $attempts++
                }
            }
            
            Write-ColorText "`nDocker Desktop is running but not responding to commands. Please check Docker status." -ForegroundColor "Red"
            return $false
        }
        
        # Docker is not running, attempt to start it
        Write-ColorText "Docker is not running. Attempting to start Docker Desktop..." -ForegroundColor "Yellow"
        
        # Docker Desktop locations to check
        $dockerPaths = @(
            "${env:ProgramFiles}\Docker\Docker\Docker Desktop.exe",
            "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
            "$env:LOCALAPPDATA\Docker\Docker\Docker Desktop.exe"
        )
        
        $dockerPath = $null
        foreach ($path in $dockerPaths) {
            if (Test-Path $path) {
                $dockerPath = $path
                break
            }
        }
        
        if ($null -eq $dockerPath) {
            Write-ColorText "Docker Desktop not found. Please install Docker Desktop or start it manually." -ForegroundColor "Red"
            return $false
        }
        
        # Start Docker Desktop
        try {
            Start-Process $dockerPath
            Write-Host -NoNewline "Waiting for Docker to start"
            
            # Wait for Docker to be ready
            $attempts = 0
            $maxAttempts = 60  # 60 x 2 seconds = maximum 2 minutes wait
            
            while ($attempts -lt $maxAttempts) {
                try {
                    $null = docker ps 2>&1
                    Write-Host "`nDocker has started successfully!"
                    return $true
                } catch {
                    # Show waiting animation
                    Write-Host -NoNewline "."
                    Start-Sleep -Seconds 2
                    $attempts++
                    
                    if ($attempts % 3 -eq 0) {
                        Write-Host "`r" -NoNewline
                        Write-Host "Waiting for Docker to start   " -NoNewline
                    }
                }
            }
            
            Write-ColorText "`nDocker did not start within the expected time. Please start Docker Desktop manually." -ForegroundColor "Red"
            return $false
        } catch {
            Write-ColorText "Failed to start Docker Desktop. Please start it manually." -ForegroundColor "Red"
            return $false
        }
    } catch {
        Write-ColorText "Error checking Docker status: $_" -ForegroundColor "Red"
        return $false
    }
}

# Function to prompt the user for the main menu choice
function Prompt-MainMenu {
    Write-Host ""
    Write-ColorText "Welcome to DocsGPT Setup!" -ForegroundColor "White" -Bold
    Write-ColorText "How would you like to proceed?" -ForegroundColor "White"
    Write-ColorText "1) Use DocsGPT Public API Endpoint (simple and free, uses pre-built Docker images from Docker Hub for fastest setup)" -ForegroundColor "Yellow"
    Write-ColorText "2) Serve Local (with Ollama)" -ForegroundColor "Yellow"
    Write-ColorText "3) Connect Local Inference Engine" -ForegroundColor "Yellow"
    Write-ColorText "4) Connect Cloud API Provider" -ForegroundColor "Yellow"
    Write-ColorText "5) Advanced: Build images locally (for developers)" -ForegroundColor "Yellow"
    Write-Host ""
    Write-ColorText "By default, DocsGPT uses pre-built images from Docker Hub for a fast, reliable, and consistent experience. This avoids local build errors and speeds up onboarding. Advanced users can choose to build images locally if needed." -ForegroundColor "White"
    Write-Host ""
    $script:main_choice = Read-Host "Choose option (1-5)"
}

# Function to prompt for Local Inference Engine options
function Prompt-LocalInferenceEngineOptions {
    Clear-Host
    Write-Host ""
    Write-ColorText "Connect Local Inference Engine" -ForegroundColor "White" -Bold
    Write-ColorText "Choose your local inference engine:" -ForegroundColor "White"
    Write-ColorText "1) LLaMa.cpp" -ForegroundColor "Yellow"
    Write-ColorText "2) Ollama" -ForegroundColor "Yellow"
    Write-ColorText "3) Text Generation Inference (TGI)" -ForegroundColor "Yellow"
    Write-ColorText "4) SGLang" -ForegroundColor "Yellow"
    Write-ColorText "5) vLLM" -ForegroundColor "Yellow"
    Write-ColorText "6) Aphrodite" -ForegroundColor "Yellow"
    Write-ColorText "7) FriendliAI" -ForegroundColor "Yellow"
    Write-ColorText "8) LMDeploy" -ForegroundColor "Yellow"
    Write-ColorText "b) Back to Main Menu" -ForegroundColor "Yellow"
    Write-Host ""
    $script:engine_choice = Read-Host "Choose option (1-8, or b)"
}

# Function to prompt for Cloud API Provider options
function Prompt-CloudAPIProviderOptions {
    Clear-Host
    Write-Host ""
    Write-ColorText "Connect Cloud API Provider" -ForegroundColor "White" -Bold
    Write-ColorText "Choose your Cloud API Provider:" -ForegroundColor "White"
    Write-ColorText "1) OpenAI" -ForegroundColor "Yellow"
    Write-ColorText "2) Google (Vertex AI, Gemini)" -ForegroundColor "Yellow"
    Write-ColorText "3) Anthropic (Claude)" -ForegroundColor "Yellow"
    Write-ColorText "4) Groq" -ForegroundColor "Yellow"
    Write-ColorText "5) HuggingFace Inference API" -ForegroundColor "Yellow"
    Write-ColorText "6) Azure OpenAI" -ForegroundColor "Yellow"
    Write-ColorText "7) Novita" -ForegroundColor "Yellow"
    Write-ColorText "b) Back to Main Menu" -ForegroundColor "Yellow"
    Write-Host ""
    $script:provider_choice = Read-Host "Choose option (1-7, or b)"
}

# Function to prompt for Ollama CPU/GPU options
function Prompt-OllamaOptions {
    Clear-Host
    Write-Host ""
    Write-ColorText "Serve Local with Ollama" -ForegroundColor "White" -Bold
    Write-ColorText "Choose how to serve Ollama:" -ForegroundColor "White"
    Write-ColorText "1) CPU" -ForegroundColor "Yellow"
    Write-ColorText "2) GPU" -ForegroundColor "Yellow"
    Write-ColorText "b) Back to Main Menu" -ForegroundColor "Yellow"
    Write-Host ""
    $script:ollama_choice = Read-Host "Choose option (1-2, or b)"
}

# ========================
# Advanced Settings Functions
# ========================

# Vector Store configuration
function Configure-VectorStore {
    Write-Host ""
    Write-ColorText "Vector Store Configuration" -ForegroundColor "White" -Bold
    Write-ColorText "Choose your vector store:" -ForegroundColor "White"
    Write-ColorText "1) FAISS (default, local)" -ForegroundColor "Yellow"
    Write-ColorText "2) Elasticsearch" -ForegroundColor "Yellow"
    Write-ColorText "3) Qdrant" -ForegroundColor "Yellow"
    Write-ColorText "4) Milvus" -ForegroundColor "Yellow"
    Write-ColorText "5) LanceDB" -ForegroundColor "Yellow"
    Write-ColorText "6) PGVector" -ForegroundColor "Yellow"
    Write-ColorText "b) Back" -ForegroundColor "Yellow"
    Write-Host ""
    $vs_choice = Read-Host "Choose option (1-6, or b)"

    switch ($vs_choice) {
        "1" {
            "VECTOR_STORE=faiss" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Vector store set to FAISS." -ForegroundColor "Green"
        }
        "2" {
            "VECTOR_STORE=elasticsearch" | Add-Content -Path $ENV_FILE -Encoding utf8
            $elastic_url = Read-Host "Enter Elasticsearch URL (e.g. http://localhost:9200)"
            if ($elastic_url) { "ELASTIC_URL=$elastic_url" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $elastic_cloud_id = Read-Host "Enter Elasticsearch Cloud ID (leave empty if using URL)"
            if ($elastic_cloud_id) { "ELASTIC_CLOUD_ID=$elastic_cloud_id" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $elastic_user = Read-Host "Enter Elasticsearch username (leave empty if none)"
            if ($elastic_user) { "ELASTIC_USERNAME=$elastic_user" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $elastic_pass = Read-Host "Enter Elasticsearch password (leave empty if none)"
            if ($elastic_pass) { "ELASTIC_PASSWORD=$elastic_pass" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $elastic_index = Read-Host "Enter Elasticsearch index name (default: docsgpt)"
            if ([string]::IsNullOrEmpty($elastic_index)) { $elastic_index = "docsgpt" }
            "ELASTIC_INDEX=$elastic_index" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Vector store set to Elasticsearch." -ForegroundColor "Green"
        }
        "3" {
            "VECTOR_STORE=qdrant" | Add-Content -Path $ENV_FILE -Encoding utf8
            $qdrant_url = Read-Host "Enter Qdrant URL (e.g. http://localhost:6333)"
            if ($qdrant_url) { "QDRANT_URL=$qdrant_url" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $qdrant_key = Read-Host "Enter Qdrant API key (leave empty if none)"
            if ($qdrant_key) { "QDRANT_API_KEY=$qdrant_key" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $qdrant_collection = Read-Host "Enter Qdrant collection name (default: docsgpt)"
            if ([string]::IsNullOrEmpty($qdrant_collection)) { $qdrant_collection = "docsgpt" }
            "QDRANT_COLLECTION_NAME=$qdrant_collection" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Vector store set to Qdrant." -ForegroundColor "Green"
        }
        "4" {
            "VECTOR_STORE=milvus" | Add-Content -Path $ENV_FILE -Encoding utf8
            $milvus_uri = Read-Host "Enter Milvus URI (default: ./milvus_local.db)"
            if ([string]::IsNullOrEmpty($milvus_uri)) { $milvus_uri = "./milvus_local.db" }
            "MILVUS_URI=$milvus_uri" | Add-Content -Path $ENV_FILE -Encoding utf8
            $milvus_token = Read-Host "Enter Milvus token (leave empty if none)"
            if ($milvus_token) { "MILVUS_TOKEN=$milvus_token" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $milvus_collection = Read-Host "Enter Milvus collection name (default: docsgpt)"
            if ([string]::IsNullOrEmpty($milvus_collection)) { $milvus_collection = "docsgpt" }
            "MILVUS_COLLECTION_NAME=$milvus_collection" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Vector store set to Milvus." -ForegroundColor "Green"
        }
        "5" {
            "VECTOR_STORE=lancedb" | Add-Content -Path $ENV_FILE -Encoding utf8
            $lancedb_path = Read-Host "Enter LanceDB path (default: ./data/lancedb)"
            if ([string]::IsNullOrEmpty($lancedb_path)) { $lancedb_path = "./data/lancedb" }
            "LANCEDB_PATH=$lancedb_path" | Add-Content -Path $ENV_FILE -Encoding utf8
            $lancedb_table = Read-Host "Enter LanceDB table name (default: docsgpts)"
            if ([string]::IsNullOrEmpty($lancedb_table)) { $lancedb_table = "docsgpts" }
            "LANCEDB_TABLE_NAME=$lancedb_table" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Vector store set to LanceDB." -ForegroundColor "Green"
        }
        "6" {
            "VECTOR_STORE=pgvector" | Add-Content -Path $ENV_FILE -Encoding utf8
            $pgvector_conn = Read-Host "Enter PGVector connection string (e.g. postgresql://user:pass@host:5432/db)"
            if ($pgvector_conn) { "PGVECTOR_CONNECTION_STRING=$pgvector_conn" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "Vector store set to PGVector." -ForegroundColor "Green"
        }
        {$_ -eq "b" -or $_ -eq "B"} { return }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
}

# Embeddings configuration
function Configure-Embeddings {
    Write-Host ""
    Write-ColorText "Embeddings Configuration" -ForegroundColor "White" -Bold
    Write-ColorText "Choose your embeddings provider:" -ForegroundColor "White"
    Write-ColorText "1) HuggingFace (default, local)" -ForegroundColor "Yellow"
    Write-ColorText "2) OpenAI Embeddings" -ForegroundColor "Yellow"
    Write-ColorText "3) Custom Remote Embeddings (OpenAI-compatible API)" -ForegroundColor "Yellow"
    Write-ColorText "b) Back" -ForegroundColor "Yellow"
    Write-Host ""
    $emb_choice = Read-Host "Choose option (1-3, or b)"

    switch ($emb_choice) {
        "1" {
            "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Embeddings set to HuggingFace (local)." -ForegroundColor "Green"
        }
        "2" {
            "EMBEDDINGS_NAME=openai_text-embedding-ada-002" | Add-Content -Path $ENV_FILE -Encoding utf8
            $emb_key = Read-Host "Enter Embeddings API key (leave empty to reuse LLM API_KEY)"
            if ($emb_key) { "EMBEDDINGS_KEY=$emb_key" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "Embeddings set to OpenAI." -ForegroundColor "Green"
        }
        "3" {
            $emb_name = Read-Host "Enter embeddings model name"
            if ($emb_name) { "EMBEDDINGS_NAME=$emb_name" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $emb_url = Read-Host "Enter remote embeddings API base URL"
            if ($emb_url) { "EMBEDDINGS_BASE_URL=$emb_url" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $emb_key = Read-Host "Enter embeddings API key (leave empty if none)"
            if ($emb_key) { "EMBEDDINGS_KEY=$emb_key" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "Custom remote embeddings configured." -ForegroundColor "Green"
        }
        {$_ -eq "b" -or $_ -eq "B"} { return }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
}

# Authentication configuration
function Configure-Auth {
    Write-Host ""
    Write-ColorText "Authentication Configuration" -ForegroundColor "White" -Bold
    Write-ColorText "Choose authentication type:" -ForegroundColor "White"
    Write-ColorText "1) None (default, no authentication)" -ForegroundColor "Yellow"
    Write-ColorText "2) Simple JWT" -ForegroundColor "Yellow"
    Write-ColorText "3) Session JWT" -ForegroundColor "Yellow"
    Write-ColorText "b) Back" -ForegroundColor "Yellow"
    Write-Host ""
    $auth_choice = Read-Host "Choose option (1-3, or b)"

    switch ($auth_choice) {
        "1" {
            Write-ColorText "Authentication disabled (default)." -ForegroundColor "Green"
        }
        "2" {
            "AUTH_TYPE=simple_jwt" | Add-Content -Path $ENV_FILE -Encoding utf8
            $jwt_key = Read-Host "Enter JWT secret key (leave empty to auto-generate)"
            if ([string]::IsNullOrEmpty($jwt_key)) {
                $bytes = New-Object byte[] 32
                [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
                $jwt_key = [System.BitConverter]::ToString($bytes).Replace("-", "").ToLower()
                Write-ColorText "Auto-generated JWT secret key." -ForegroundColor "Yellow"
            }
            "JWT_SECRET_KEY=$jwt_key" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Authentication set to Simple JWT." -ForegroundColor "Green"
        }
        "3" {
            "AUTH_TYPE=session_jwt" | Add-Content -Path $ENV_FILE -Encoding utf8
            $jwt_key = Read-Host "Enter JWT secret key (leave empty to auto-generate)"
            if ([string]::IsNullOrEmpty($jwt_key)) {
                $bytes = New-Object byte[] 32
                [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
                $jwt_key = [System.BitConverter]::ToString($bytes).Replace("-", "").ToLower()
                Write-ColorText "Auto-generated JWT secret key." -ForegroundColor "Yellow"
            }
            "JWT_SECRET_KEY=$jwt_key" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "Authentication set to Session JWT." -ForegroundColor "Green"
        }
        {$_ -eq "b" -or $_ -eq "B"} { return }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
}

# Integrations configuration
function Configure-Integrations {
    Write-Host ""
    Write-ColorText "Integrations Configuration" -ForegroundColor "White" -Bold
    Write-ColorText "1) Google Drive" -ForegroundColor "Yellow"
    Write-ColorText "2) GitHub" -ForegroundColor "Yellow"
    Write-ColorText "b) Back" -ForegroundColor "Yellow"
    Write-Host ""
    $int_choice = Read-Host "Choose option (1-2, or b)"

    switch ($int_choice) {
        "1" {
            $google_id = Read-Host "Enter Google OAuth Client ID"
            if ($google_id) { "GOOGLE_CLIENT_ID=$google_id" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            $google_secret = Read-Host "Enter Google OAuth Client Secret"
            if ($google_secret) { "GOOGLE_CLIENT_SECRET=$google_secret" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "Google Drive integration configured." -ForegroundColor "Green"
        }
        "2" {
            $github_token = Read-Host "Enter GitHub Personal Access Token (with repo read access)"
            if ($github_token) { "GITHUB_ACCESS_TOKEN=$github_token" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "GitHub integration configured." -ForegroundColor "Green"
        }
        {$_ -eq "b" -or $_ -eq "B"} { return }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
}

# Document Processing configuration
function Configure-DocProcessing {
    Write-Host ""
    Write-ColorText "Document Processing Configuration" -ForegroundColor "White" -Bold
    $pdf_image = Read-Host "Parse PDF pages as images for better table/chart extraction? (y/N)"
    if ($pdf_image -eq "y" -or $pdf_image -eq "Y") {
        "PARSE_PDF_AS_IMAGE=true" | Add-Content -Path $ENV_FILE -Encoding utf8
        Write-ColorText "PDF-as-image parsing enabled." -ForegroundColor "Green"
    }

    $ocr_enabled = Read-Host "Enable OCR for document processing (Docling)? (y/N)"
    if ($ocr_enabled -eq "y" -or $ocr_enabled -eq "Y") {
        "DOCLING_OCR_ENABLED=true" | Add-Content -Path $ENV_FILE -Encoding utf8
        Write-ColorText "Docling OCR enabled." -ForegroundColor "Green"
    }
}

# Text-to-Speech configuration
function Configure-TTS {
    Write-Host ""
    Write-ColorText "Text-to-Speech Configuration" -ForegroundColor "White" -Bold
    Write-ColorText "Choose TTS provider:" -ForegroundColor "White"
    Write-ColorText "1) Google TTS (default, free)" -ForegroundColor "Yellow"
    Write-ColorText "2) ElevenLabs" -ForegroundColor "Yellow"
    Write-ColorText "b) Back" -ForegroundColor "Yellow"
    Write-Host ""
    $tts_choice = Read-Host "Choose option (1-2, or b)"

    switch ($tts_choice) {
        "1" {
            "TTS_PROVIDER=google_tts" | Add-Content -Path $ENV_FILE -Encoding utf8
            Write-ColorText "TTS set to Google TTS." -ForegroundColor "Green"
        }
        "2" {
            "TTS_PROVIDER=elevenlabs" | Add-Content -Path $ENV_FILE -Encoding utf8
            $elevenlabs_key = Read-Host "Enter ElevenLabs API key"
            if ($elevenlabs_key) { "ELEVENLABS_API_KEY=$elevenlabs_key" | Add-Content -Path $ENV_FILE -Encoding utf8 }
            Write-ColorText "TTS set to ElevenLabs." -ForegroundColor "Green"
        }
        {$_ -eq "b" -or $_ -eq "B"} { return }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
}

# Main advanced settings menu
function Prompt-AdvancedSettings {
    Write-Host ""
    $configure_advanced = Read-Host "Would you like to configure advanced settings? (y/N)"
    if ($configure_advanced -ne "y" -and $configure_advanced -ne "Y") {
        return
    }

    while ($true) {
        Write-Host ""
        Write-ColorText "Advanced Settings" -ForegroundColor "White" -Bold
        Write-ColorText "1) Vector Store         (default: faiss)" -ForegroundColor "Yellow"
        Write-ColorText "2) Embeddings           (default: HuggingFace local)" -ForegroundColor "Yellow"
        Write-ColorText "3) Authentication       (default: none)" -ForegroundColor "Yellow"
        Write-ColorText "4) Integrations         (Google Drive, GitHub)" -ForegroundColor "Yellow"
        Write-ColorText "5) Document Processing  (PDF as image, OCR)" -ForegroundColor "Yellow"
        Write-ColorText "6) Text-to-Speech       (default: Google TTS)" -ForegroundColor "Yellow"
        Write-ColorText "s) Save and Continue with Docker setup" -ForegroundColor "Yellow"
        Write-Host ""
        $adv_choice = Read-Host "Choose option (1-6, or s)"

        switch ($adv_choice) {
            "1" { Configure-VectorStore }
            "2" { Configure-Embeddings }
            "3" { Configure-Auth }
            "4" { Configure-Integrations }
            "5" { Configure-DocProcessing }
            "6" { Configure-TTS }
            {$_ -eq "s" -or $_ -eq "S"} { break }
            default {
                Write-Host ""
                Write-ColorText "Invalid choice." -ForegroundColor "Red"
                Start-Sleep -Seconds 1
            }
        }
    }
}

# 1) Use DocsGPT Public API Endpoint (simple and free)
function Use-DocsPublicAPIEndpoint {
    Write-Host ""
    Write-ColorText "Setting up DocsGPT Public API Endpoint..." -ForegroundColor "White"
    
    # Create .env file
    "LLM_PROVIDER=docsgpt" | Out-File -FilePath $ENV_FILE -Encoding utf8 -Force
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for DocsGPT Public API." -ForegroundColor "Green"

    Prompt-AdvancedSettings

    # Start Docker if needed
    $dockerRunning = Check-AndStartDocker
    if (-not $dockerRunning) {
        Write-ColorText "Docker is required but could not be started. Please start Docker Desktop manually and try again." -ForegroundColor "Red"
        return
    }

    Write-Host ""
    Write-ColorText "Starting Docker Compose..." -ForegroundColor "White"
    
    # Run Docker compose commands
    try {
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose pull failed with exit code $LASTEXITCODE"
        }
        
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose up failed with exit code $LASTEXITCODE"
        }
        
        Write-Host ""
        Write-ColorText "DocsGPT is now running on http://localhost:5173" -ForegroundColor "Green"
        Write-ColorText "You can stop the application by running: docker compose -f `"$COMPOSE_FILE`" down" -ForegroundColor "Yellow"
    }
    catch {
        Write-Host ""
        Write-ColorText "Error starting Docker Compose: $_" -ForegroundColor "Red"
        Write-ColorText "Please ensure Docker Compose is installed and in your PATH." -ForegroundColor "Red"
        Write-ColorText "Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/" -ForegroundColor "Red"
        exit 1  # Exit script with error
    }
}

# 2) Serve Local (with Ollama)
function Serve-LocalOllama {
    $script:model_name = ""
    $default_model = "llama3.2:1b"
    $docker_compose_file_suffix = ""
    
    function Get-ModelNameOllama {
        $model_name_input = Read-Host "Enter Ollama Model Name (press Enter for default: $default_model (1.3GB))"
        if ([string]::IsNullOrEmpty($model_name_input)) {
            $script:model_name = $default_model
        } else {
            $script:model_name = $model_name_input
        }
    }

    while ($true) {
        Clear-Host
        Prompt-OllamaOptions
        
        switch ($ollama_choice) {
            "1" {  # CPU
                $docker_compose_file_suffix = "cpu"
                Get-ModelNameOllama
                break
            }
            "2" {  # GPU
                Write-Host ""
                Write-ColorText "For this option to work correctly you need to have a supported GPU and configure Docker to utilize it." -ForegroundColor "Yellow"
                Write-ColorText "Refer to: https://hub.docker.com/r/ollama/ollama for more information." -ForegroundColor "Yellow"
                $confirm_gpu = Read-Host "Continue with GPU setup? (y/b)"
                
                if ($confirm_gpu -eq "y" -or $confirm_gpu -eq "Y") {
                    $docker_compose_file_suffix = "gpu"
                    Get-ModelNameOllama
                    break
                } 
                elseif ($confirm_gpu -eq "b" -or $confirm_gpu -eq "B") {
                    $script:ollama_choice = "b"
                    Clear-Host
                    return
                } 
                else {
                    Write-Host ""
                    Write-ColorText "Invalid choice. Please choose y or b." -ForegroundColor "Red"
                    Start-Sleep -Seconds 1
                }
            }
            "b" { Clear-Host; return }
            "B" { Clear-Host; return }
            default {
                Write-Host ""
                Write-ColorText "Invalid choice. Please choose 1-2, or b." -ForegroundColor "Red"
                Start-Sleep -Seconds 1
            }
        }
        
        if (-not [string]::IsNullOrEmpty($docker_compose_file_suffix)) {
            break
        }
    }

    Write-Host ""
    Write-ColorText "Configuring for Ollama ($($docker_compose_file_suffix.ToUpper()))..." -ForegroundColor "White"
    
    # Create .env file
    "API_KEY=xxxx" | Out-File -FilePath $ENV_FILE -Encoding utf8 -Force
    "LLM_PROVIDER=openai" | Add-Content -Path $ENV_FILE -Encoding utf8
    "LLM_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    "OPENAI_BASE_URL=http://ollama:11434/v1" | Add-Content -Path $ENV_FILE -Encoding utf8
    "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for Ollama ($($docker_compose_file_suffix.ToUpper()))." -ForegroundColor "Green"
    Write-ColorText "Note: MODEL_NAME is set to '$model_name'. You can change it later in the .env file." -ForegroundColor "Yellow"

    Prompt-AdvancedSettings

    # Start Docker if needed
    $dockerRunning = Check-AndStartDocker
    if (-not $dockerRunning) {
        Write-ColorText "Docker is required but could not be started. Please start Docker Desktop manually and try again." -ForegroundColor "Red"
        return
    }

    # Setup compose file paths
    $optional_compose = Join-Path -Path (Split-Path -Parent $COMPOSE_FILE) -ChildPath "optional\docker-compose.optional.ollama-$docker_compose_file_suffix.yaml"
    
    try {
        Write-Host ""
        Write-ColorText "Starting Docker Compose with Ollama ($docker_compose_file_suffix)..." -ForegroundColor "White"
        
        # Pull the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$optional_compose" pull
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose pull failed with exit code $LASTEXITCODE"
        }
        
        # Start the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$optional_compose" up -d
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose up failed with exit code $LASTEXITCODE"
        }
        
        # Wait for Ollama container to be ready
        Write-ColorText "Waiting for Ollama container to be ready..." -ForegroundColor "White"
        $ollamaReady = $false
        $maxAttempts = 30  # Maximum number of attempts (30 x 5 seconds = 2.5 minutes)
        $attempts = 0
        
        while (-not $ollamaReady -and $attempts -lt $maxAttempts) {
            $containerStatus = & docker compose -f "$COMPOSE_FILE" -f "$optional_compose" ps --services --filter "status=running" --format "{{.Service}}"
            
            if ($containerStatus -like "*ollama*") {
                $ollamaReady = $true
                Write-ColorText "Ollama container is running." -ForegroundColor "Green"
            } else {
                Write-Host "Ollama container not yet ready, waiting... (Attempt $($attempts+1)/$maxAttempts)"
                Start-Sleep -Seconds 5
                $attempts++
            }
        }
        
        if (-not $ollamaReady) {
            Write-ColorText "Ollama container did not start within the expected time. Please check Docker logs for errors." -ForegroundColor "Red"
            return
        }
        
        # Pull the Ollama model
        Write-ColorText "Pulling $model_name model for Ollama..." -ForegroundColor "White"
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$optional_compose" exec -it ollama ollama pull "$model_name"
        
        Write-Host ""
        Write-ColorText "DocsGPT is now running with Ollama ($docker_compose_file_suffix) on http://localhost:5173" -ForegroundColor "Green"
        Write-ColorText "You can stop the application by running: docker compose -f `"$COMPOSE_FILE`" -f `"$optional_compose`" down" -ForegroundColor "Yellow"
    }
    catch {
        Write-Host ""
        Write-ColorText "Error running Docker Compose: $_" -ForegroundColor "Red"
        Write-ColorText "Please ensure Docker Compose is installed and in your PATH." -ForegroundColor "Red"
        Write-ColorText "Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/" -ForegroundColor "Red"
        exit 1
    }
}

# 3) Connect Local Inference Engine
function Connect-LocalInferenceEngine {
    $script:engine_name = ""
    $script:openai_base_url = ""
    $script:model_name = ""
    
    function Get-ModelName {
        $model_name_input = Read-Host "Enter Model Name (press Enter for None)"
        if ([string]::IsNullOrEmpty($model_name_input)) {
            $script:model_name = "None"
        } else {
            $script:model_name = $model_name_input
        }
    }

    while ($true) {
        Clear-Host
        Prompt-LocalInferenceEngineOptions
        
        switch ($engine_choice) {
            "1" {  # LLaMa.cpp
                $script:engine_name = "LLaMa.cpp"
                $script:openai_base_url = "http://host.docker.internal:8000/v1"
                Get-ModelName
                break
            }
            "2" {  # Ollama
                $script:engine_name = "Ollama"
                $script:openai_base_url = "http://host.docker.internal:11434/v1"
                Get-ModelName
                break
            }
            "3" {  # TGI
                $script:engine_name = "TGI"
                $script:openai_base_url = "http://host.docker.internal:8080/v1"
                Get-ModelName
                break
            }
            "4" {  # SGLang
                $script:engine_name = "SGLang"
                $script:openai_base_url = "http://host.docker.internal:30000/v1"
                Get-ModelName
                break
            }
            "5" {  # vLLM
                $script:engine_name = "vLLM"
                $script:openai_base_url = "http://host.docker.internal:8000/v1"
                Get-ModelName
                break
            }
            "6" {  # Aphrodite
                $script:engine_name = "Aphrodite"
                $script:openai_base_url = "http://host.docker.internal:2242/v1"
                Get-ModelName
                break
            }
            "7" {  # FriendliAI
                $script:engine_name = "FriendliAI"
                $script:openai_base_url = "http://host.docker.internal:8997/v1"
                Get-ModelName
                break
            }
            "8" {  # LMDeploy
                $script:engine_name = "LMDeploy"
                $script:openai_base_url = "http://host.docker.internal:23333/v1"
                Get-ModelName
                break
            }
            "b" { Clear-Host; return }
            "B" { Clear-Host; return }
            default {
                Write-Host ""
                Write-ColorText "Invalid choice. Please choose 1-8, or b." -ForegroundColor "Red"
                Start-Sleep -Seconds 1
            }
        }
        
        if (-not [string]::IsNullOrEmpty($script:engine_name)) {
            break
        }
    }

    Write-Host ""
    Write-ColorText "Configuring for Local Inference Engine: $engine_name..." -ForegroundColor "White"
    
    # Create .env file
    "API_KEY=None" | Out-File -FilePath $ENV_FILE -Encoding utf8 -Force
    "LLM_PROVIDER=openai" | Add-Content -Path $ENV_FILE -Encoding utf8
    "LLM_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    "OPENAI_BASE_URL=$openai_base_url" | Add-Content -Path $ENV_FILE -Encoding utf8
    "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for $engine_name with OpenAI API format." -ForegroundColor "Green"
    Write-ColorText "Note: MODEL_NAME is set to '$model_name'. You can change it later in the .env file." -ForegroundColor "Yellow"

    Prompt-AdvancedSettings

    # Start Docker if needed
    $dockerRunning = Check-AndStartDocker
    if (-not $dockerRunning) {
        Write-ColorText "Docker is required but could not be started. Please start Docker Desktop manually and try again." -ForegroundColor "Red"
        return
    }

    try {
        Write-Host ""
        Write-ColorText "Starting Docker Compose..." -ForegroundColor "White"
        
        # Pull the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose pull failed with exit code $LASTEXITCODE"
        }
        
        # Start the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose up failed with exit code $LASTEXITCODE"
        }
        
        Write-Host ""
        Write-ColorText "DocsGPT is now configured to connect to $engine_name at $openai_base_url" -ForegroundColor "Green"
        Write-ColorText "Ensure your $engine_name inference server is running at that address" -ForegroundColor "Yellow"
        Write-Host ""
        Write-ColorText "DocsGPT is running at http://localhost:5173" -ForegroundColor "Green"
        Write-ColorText "You can stop the application by running: docker compose -f `"$COMPOSE_FILE`" down" -ForegroundColor "Yellow"
    }
    catch {
        Write-Host ""
        Write-ColorText "Error running Docker Compose: $_" -ForegroundColor "Red"
        Write-ColorText "Please ensure Docker Compose is installed and in your PATH." -ForegroundColor "Red"
        Write-ColorText "Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/" -ForegroundColor "Red"
        exit 1
    }
}

# 4) Connect Cloud API Provider
function Connect-CloudAPIProvider {
    $script:provider_name = ""
    $script:llm_name = ""
    $script:model_name = ""
    $script:api_key = ""
    
    function Get-APIKey {
        Write-ColorText "Your API key will be stored locally in the .env file and will not be sent anywhere else" -ForegroundColor "Yellow"
        $script:api_key = Read-Host "Please enter your API key"
    }

    while ($true) {
        Clear-Host
        Prompt-CloudAPIProviderOptions
        
        switch ($provider_choice) {
            "1" {  # OpenAI
                $script:provider_name = "OpenAI"
                $script:llm_name = "openai"
                $script:model_name = "gpt-4o"
                Get-APIKey
                break
            }
            "2" {  # Google
                $script:provider_name = "Google (Vertex AI, Gemini)"
                $script:llm_name = "google"
                $script:model_name = "gemini-2.0-flash"
                Get-APIKey
                break
            }
            "3" {  # Anthropic
                $script:provider_name = "Anthropic (Claude)"
                $script:llm_name = "anthropic"
                $script:model_name = "claude-3-5-sonnet-latest"
                Get-APIKey
                break
            }
            "4" {  # Groq
                $script:provider_name = "Groq"
                $script:llm_name = "groq"
                $script:model_name = "llama-3.1-8b-instant" 
                Get-APIKey
                break
            }
            "5" {  # HuggingFace Inference API
                $script:provider_name = "HuggingFace Inference API"
                $script:llm_name = "huggingface"
                $script:model_name = "meta-llama/Llama-3.1-8B-Instruct"
                Get-APIKey
                break
            }
            "6" {  # Azure OpenAI
                $script:provider_name = "Azure OpenAI"
                $script:llm_name = "azure_openai"
                $script:model_name = "gpt-4o"
                Get-APIKey
                Write-Host ""
                Write-ColorText "Azure OpenAI requires additional configuration:" -ForegroundColor "White" -Bold
                $script:azure_api_base = Read-Host "Enter Azure OpenAI API base URL (e.g. https://your-resource.openai.azure.com/)"
                $script:azure_api_version = Read-Host "Enter Azure OpenAI API version (e.g. 2024-02-15-preview)"
                $script:azure_deployment = Read-Host "Enter Azure deployment name for chat"
                $script:azure_emb_deployment = Read-Host "Enter Azure deployment name for embeddings (leave empty to skip)"
                break
            }
            "7" {  # Novita
                $script:provider_name = "Novita"
                $script:llm_name = "novita"
                $script:model_name = "deepseek/deepseek-r1"
                Get-APIKey
                break
            }
            "b" { Clear-Host; return }
            "B" { Clear-Host; return }
            default {
                Write-Host ""
                Write-ColorText "Invalid choice. Please choose 1-7, or b." -ForegroundColor "Red"
                Start-Sleep -Seconds 1
            }
        }
        
        if (-not [string]::IsNullOrEmpty($script:provider_name)) {
            break
        }
    }

    Write-Host ""
    Write-ColorText "Configuring for Cloud API Provider: $provider_name..." -ForegroundColor "White"
    
    # Create .env file
    "API_KEY=$api_key" | Out-File -FilePath $ENV_FILE -Encoding utf8 -Force
    "LLM_PROVIDER=$llm_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "LLM_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8

    # Azure OpenAI additional settings
    if ($llm_name -eq "azure_openai") {
        if ($azure_api_base) { "OPENAI_API_BASE=$azure_api_base" | Add-Content -Path $ENV_FILE -Encoding utf8 }
        if ($azure_api_version) { "OPENAI_API_VERSION=$azure_api_version" | Add-Content -Path $ENV_FILE -Encoding utf8 }
        if ($azure_deployment) { "AZURE_DEPLOYMENT_NAME=$azure_deployment" | Add-Content -Path $ENV_FILE -Encoding utf8 }
        if ($azure_emb_deployment) { "AZURE_EMBEDDINGS_DEPLOYMENT_NAME=$azure_emb_deployment" | Add-Content -Path $ENV_FILE -Encoding utf8 }
    }

    Write-ColorText ".env file configured for $provider_name." -ForegroundColor "Green"

    Prompt-AdvancedSettings

    # Start Docker if needed
    $dockerRunning = Check-AndStartDocker
    if (-not $dockerRunning) {
        Write-ColorText "Docker is required but could not be started. Please start Docker Desktop manually and try again." -ForegroundColor "Red"
        return
    }

    try {
        Write-Host ""
        Write-ColorText "Starting Docker Compose..." -ForegroundColor "White"

        # Run Docker compose commands
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose pull failed with exit code $LASTEXITCODE"
        }

         & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

        Write-Host ""
        Write-ColorText "DocsGPT is now configured to use $provider_name on http://localhost:5173" -ForegroundColor "Green"
        Write-ColorText "You can stop the application by running: docker compose -f `"$COMPOSE_FILE`" down" -ForegroundColor "Yellow"
    }
    catch {
        Write-Host ""
        Write-ColorText "Error running Docker Compose: $_" -ForegroundColor "Red"
        Write-ColorText "Please ensure Docker Compose is installed and in your PATH." -ForegroundColor "Red"
        Write-ColorText "Refer to Docker documentation for installation instructions: https://docs.docker.com/compose/install/" -ForegroundColor "Red"
        exit 1
    }
}

# Main script execution
Animate-Dino

# Check if .env file exists and is not empty
if ((Test-Path $ENV_FILE) -and ((Get-Item $ENV_FILE).Length -gt 0)) {
    Write-Host ""
    Write-ColorText "Warning: An existing .env file was found with the following settings:" -ForegroundColor "Yellow" -Bold
    $envLines = Get-Content $ENV_FILE
    $envLines | Select-Object -First 3 | ForEach-Object { Write-Host "  $_" }
    if ($envLines.Count -gt 3) {
        Write-Host "  ... and $($envLines.Count - 3) more lines"
    }
    Write-Host ""
    $confirm_overwrite = Read-Host "Running setup will overwrite this file. Continue? (y/N)"
    if ($confirm_overwrite -ne "y" -and $confirm_overwrite -ne "Y") {
        Write-ColorText "Setup cancelled. Your .env file was not modified." -ForegroundColor "Green"
        exit 0
    }
}

while ($true) {
    Clear-Host
    Prompt-MainMenu
    
    $exitLoop = $false  # Add this flag
    
    switch ($main_choice) {
        "1" { 
            $COMPOSE_FILE = $COMPOSE_FILE_HUB
            Use-DocsPublicAPIEndpoint
            $exitLoop = $true  # Set flag to true on completion
            break 
        }
        "2" { 
            Serve-LocalOllama
            if ($ollama_choice -ne "b" -and $ollama_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        "3" { 
            Connect-LocalInferenceEngine
            if ($engine_choice -ne "b" -and $engine_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        "4" { 
            Connect-CloudAPIProvider
            if ($provider_choice -ne "b" -and $provider_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        "5" {
            Write-Host ""
            Write-ColorText "You have selected to build images locally. This is recommended for developers or if you want to test local changes." -ForegroundColor "Yellow"
            $COMPOSE_FILE = $COMPOSE_FILE_LOCAL
            Use-DocsPublicAPIEndpoint
            $exitLoop = $true
            break
        }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice. Please choose 1-5." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
    if ($exitLoop) {
        break
    }
}

Write-Host ""
Write-ColorText "DocsGPT Setup Complete." -ForegroundColor "Green"

exit 0