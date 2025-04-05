# DocsGPT Setup PowerShell Script for Windows
# PowerShell -ExecutionPolicy Bypass -File .\setup.ps1

# Script execution policy - uncomment if needed
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force

# Set error action preference
$ErrorActionPreference = "Stop"

# Get current script directory
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Definition
$COMPOSE_FILE = Join-Path -Path $SCRIPT_DIR -ChildPath "deployment\docker-compose.yaml"
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
    Write-ColorText "1) Use DocsGPT Public API Endpoint (simple and free)" -ForegroundColor "Yellow"
    Write-ColorText "2) Serve Local (with Ollama)" -ForegroundColor "Yellow"
    Write-ColorText "3) Connect Local Inference Engine" -ForegroundColor "Yellow"
    Write-ColorText "4) Connect Cloud API Provider" -ForegroundColor "Yellow"
    Write-Host ""
    $script:main_choice = Read-Host "Choose option (1-4)"
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

# 1) Use DocsGPT Public API Endpoint (simple and free)
function Use-DocsPublicAPIEndpoint {
    Write-Host ""
    Write-ColorText "Setting up DocsGPT Public API Endpoint..." -ForegroundColor "White"
    
    # Create .env file
    "LLM_NAME=docsgpt" | Out-File -FilePath $ENV_FILE -Encoding utf8 -Force
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for DocsGPT Public API." -ForegroundColor "Green"

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
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose build failed with exit code $LASTEXITCODE"
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
    "LLM_NAME=openai" | Add-Content -Path $ENV_FILE -Encoding utf8
    "MODEL_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    "OPENAI_BASE_URL=http://host.docker.internal:11434/v1" | Add-Content -Path $ENV_FILE -Encoding utf8
    "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for Ollama ($($docker_compose_file_suffix.ToUpper()))." -ForegroundColor "Green"
    Write-ColorText "Note: MODEL_NAME is set to '$model_name'. You can change it later in the .env file." -ForegroundColor "Yellow"

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
        
        # Build the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -f "$optional_compose" build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose build failed with exit code $LASTEXITCODE"
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
                $script:openai_base_url = "http://localhost:8000/v1"
                Get-ModelName
                break
            }
            "2" {  # Ollama
                $script:engine_name = "Ollama"
                $script:openai_base_url = "http://localhost:11434/v1"
                Get-ModelName
                break
            }
            "3" {  # TGI
                $script:engine_name = "TGI"
                $script:openai_base_url = "http://localhost:8080/v1"
                Get-ModelName
                break
            }
            "4" {  # SGLang
                $script:engine_name = "SGLang"
                $script:openai_base_url = "http://localhost:30000/v1"
                Get-ModelName
                break
            }
            "5" {  # vLLM
                $script:engine_name = "vLLM"
                $script:openai_base_url = "http://localhost:8000/v1"
                Get-ModelName
                break
            }
            "6" {  # Aphrodite
                $script:engine_name = "Aphrodite"
                $script:openai_base_url = "http://localhost:2242/v1"
                Get-ModelName
                break
            }
            "7" {  # FriendliAI
                $script:engine_name = "FriendliAI"
                $script:openai_base_url = "http://localhost:8997/v1"
                Get-ModelName
                break
            }
            "8" {  # LMDeploy
                $script:engine_name = "LMDeploy"
                $script:openai_base_url = "http://localhost:23333/v1"
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
    "LLM_NAME=openai" | Add-Content -Path $ENV_FILE -Encoding utf8
    "MODEL_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    "OPENAI_BASE_URL=$openai_base_url" | Add-Content -Path $ENV_FILE -Encoding utf8
    "EMBEDDINGS_NAME=huggingface_sentence-transformers/all-mpnet-base-v2" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for $engine_name with OpenAI API format." -ForegroundColor "Green"
    Write-ColorText "Note: MODEL_NAME is set to '$model_name'. You can change it later in the .env file." -ForegroundColor "Yellow"

    # Start Docker if needed
    $dockerRunning = Check-AndStartDocker
    if (-not $dockerRunning) {
        Write-ColorText "Docker is required but could not be started. Please start Docker Desktop manually and try again." -ForegroundColor "Red"
        return
    }

    try {
        Write-Host ""
        Write-ColorText "Starting Docker Compose..." -ForegroundColor "White"
        
        # Build the containers
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose build failed with exit code $LASTEXITCODE"
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
    "LLM_NAME=$llm_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "MODEL_NAME=$model_name" | Add-Content -Path $ENV_FILE -Encoding utf8
    "VITE_API_STREAMING=true" | Add-Content -Path $ENV_FILE -Encoding utf8
    
    Write-ColorText ".env file configured for $provider_name." -ForegroundColor "Green"

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
        & docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw "Docker compose build or up failed with exit code $LASTEXITCODE"
        }
        
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

while ($true) {
    Clear-Host
    Prompt-MainMenu
    
    $exitLoop = $false  # Add this flag
    
    switch ($main_choice) {
        "1" { 
            Use-DocsPublicAPIEndpoint
            $exitLoop = $true  # Set flag to true on completion
            break 
        }
        "2" { 
            Serve-LocalOllama
            # Only exit the loop if user didn't press "b" to go back
            if ($ollama_choice -ne "b" -and $ollama_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        "3" { 
            Connect-LocalInferenceEngine
            # Only exit the loop if user didn't press "b" to go back
            if ($engine_choice -ne "b" -and $engine_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        "4" { 
            Connect-CloudAPIProvider
            # Only exit the loop if user didn't press "b" to go back
            if ($provider_choice -ne "b" -and $provider_choice -ne "B") {
                $exitLoop = $true
            }
            break 
        }
        default {
            Write-Host ""
            Write-ColorText "Invalid choice. Please choose 1-4." -ForegroundColor "Red"
            Start-Sleep -Seconds 1
        }
    }
    
    # Only break out of the loop if a function completed successfully
    if ($exitLoop) {
        break
    }
}

Write-Host ""
Write-ColorText "DocsGPT Setup Complete." -ForegroundColor "Green"

exit 0