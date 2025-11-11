#!/usr/bin/env python3
"""
Helper script to create .env file for Trip Tally
Run this from the trip_tally directory: python create_env.py
"""

import os
from pathlib import Path

def create_env_file():
    env_path = Path(".env")
    
    if env_path.exists():
        print(".env file already exists!")
        return
    
    print("Creating .env file...")
    print("Please enter your Azure Computer Vision credentials:")
    
    endpoint = input("Azure CV Endpoint (e.g., https://your-resource.cognitiveservices.azure.com): ").strip()
    key = input("Azure CV Key: ").strip()
    
    env_content = f"""FLASK_SECRET_KEY=change-me

# Azure Computer Vision
AZURE_CV_ENDPOINT={endpoint}
AZURE_CV_KEY={key}

# App settings
UPLOAD_FOLDER=static/uploads
DATABASE_PATH=trip_tally.db
"""
    
    with open(env_path, "w") as f:
        f.write(env_content)
    
    print(f"Created .env file with your credentials!")
    print("You can now run: python app.py")

if __name__ == "__main__":
    create_env_file()

