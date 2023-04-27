#!/bin/bash

check_cpu_avx_support() {
  case "$(uname -s)" in
    Linux)
      if grep -q -e avx /proc/cpuinfo; then
        return 0
      else
        return 1
      fi
      ;;
    Darwin) # macOS
      if sysctl -a | grep -q -e machdep.cpu.features.*AVX; then
        return 0
      else
        return 1
      fi
      ;;
    *)
      echo "Unsupported OS"
      return 1
      ;;
  esac
}

# Check if the CPU supports AVX
if check_cpu_avx_support; then
  echo "AVX support found."
else
  echo "Error: Your CPU does not support the AVX instruction set, which is required by Mongo 5+."
  exit 1
fi



cd "$(dirname "$0")" || exit

# Create the required directories on the host machine if they don't exist
[ ! -d "./application/indexes" ] && mkdir -p ./application/indexes
[ ! -d "./application/inputs" ] && mkdir -p ./application/inputs
[ ! -d "./application/vectors" ] && mkdir -p ./application/vectors

# Build frontend and backend images
docker build -t frontend_image ./frontend
docker build -t backend_image ./application

# Run redis and mongo services
docker run -d --name redis -p 6379:6379 redis:6-alpine
docker run -d --name mongo -p 27017:27017 -v mongodb_data_container:/data/db mongo:6

# Run backend and worker services
docker run -d --name backend -p 5001:5001 \
  --link redis:redis --link mongo:mongo \
  -v $(pwd)/application/indexes:/app/indexes \
  -v $(pwd)/application/inputs:/app/inputs \
  -v $(pwd)/application/vectors:/app/vectors \
  -e API_KEY=$OPENAI_API_KEY \
  -e EMBEDDINGS_KEY=$OPENAI_API_KEY \
  -e CELERY_BROKER_URL=redis://redis:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://redis:6379/1 \
  -e MONGO_URI=mongodb://mongo:27017/docsgpt \
  backend_image

docker run -d --name worker \
  --link redis:redis --link mongo:mongo \
  -e API_KEY=$OPENAI_API_KEY \
  -e EMBEDDINGS_KEY=$OPENAI_API_KEY \
  -e CELERY_BROKER_URL=redis://redis:6379/0 \
  -e CELERY_RESULT_BACKEND=redis://redis:6379/1 \
  -e MONGO_URI=mongodb://mongo:27017/docsgpt \
  -e API_URL=http://backend:5001 \
  backend_image \
  celery -A app.celery worker -l INFO

# Run frontend service
docker run -d --name frontend -p 5173:5173 \
  --link backend:backend \
  -e VITE_API_HOST=http://localhost:5001 \
  frontend_image
