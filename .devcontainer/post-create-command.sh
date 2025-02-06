#!/bin/bash

set -e  # Exit immediately if a command exits with a non-zero status

cp -n .env-template .env || true
mkdir -p model
if [ ! -d model/all-mpnet-base-v2 ]; then
    wget -q https://d3dg1063dc54p9.cloudfront.net/models/embeddings/mpnet-base-v2.zip -O model/mpnet-base-v2.zip
    unzip -q model/mpnet-base-v2.zip -d model
    rm model/mpnet-base-v2.zip
fi
pip install -r application/requirements.txt
cd frontend
npm install --include=dev