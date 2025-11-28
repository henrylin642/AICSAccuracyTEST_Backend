import os
import base64
import json
import logging
from pathlib import Path
from google.cloud import storage
from google.oauth2 import service_account
from config import ConfigError

LOGGER = logging.getLogger(__name__)

def get_gcs_credentials():
    """
    Load Google Cloud credentials.
    Prioritizes GOOGLE_APPLICATION_CREDENTIALS path.
    If not found, checks GOOGLE_CREDENTIALS_BASE64 env var.
    """
    # 1. Try file path
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and Path(cred_path).exists():
        return service_account.Credentials.from_service_account_file(cred_path)
    
    # 2. Try Base64 string (for Render/Heroku)
    b64_creds = os.getenv("GOOGLE_CREDENTIALS_BASE64")
    if b64_creds:
        try:
            creds_json = base64.b64decode(b64_creds).decode("utf-8")
            creds_dict = json.loads(creds_json)
            return service_account.Credentials.from_service_account_info(creds_dict)
        except Exception as e:
            LOGGER.error(f"Failed to decode GOOGLE_CREDENTIALS_BASE64: {e}")
            
    return None

class GCSClient:
    def __init__(self, bucket_name: str | None = None):
        creds = get_gcs_credentials()
        if not creds:
            # Fallback to default auth (e.g. local gcloud auth) if no specific creds provided
            self.client = storage.Client()
        else:
            self.client = storage.Client(credentials=creds)
            
        self.bucket_name = bucket_name or os.getenv("GCS_BUCKET_NAME")
        if not self.bucket_name:
            raise ConfigError("GCS_BUCKET_NAME environment variable is required")
            
        self.bucket = self.client.bucket(self.bucket_name)

    def upload_file(self, source_file_path: str, destination_blob_name: str) -> str:
        """Uploads a file to the bucket and returns the public URL."""
        blob = self.bucket.blob(destination_blob_name)
        
        # Check if exists to avoid re-uploading (optional optimization)
        if not blob.exists():
            blob.upload_from_filename(source_file_path)
            LOGGER.info(f"File {source_file_path} uploaded to {destination_blob_name}.")
        else:
            LOGGER.info(f"File {destination_blob_name} already exists in GCS.")
            
        # Make public (optional, or use signed URLs)
        # For this demo, we assume the bucket or object is readable or we make it public
        # Note: making individual objects public requires appropriate permissions
        # blob.make_public() 
        
        return blob.public_url

    def exists(self, blob_name: str) -> bool:
        blob = self.bucket.blob(blob_name)
        return blob.exists()
