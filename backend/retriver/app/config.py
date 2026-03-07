import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseSettings):
    AZURE_OPENAI_API_KEY:str = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_DEPLOYEMNT: Optional[str] = os.getenv("AZURE_OPENAI_DEPLOYEMNT")
    
    API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION")
    
    AZURE_OPENAI_API_KEY_EMBEDDING: str = os.getenv("AZURE_OPENAI_API_KEY_EMBEDDING")
    AZURE_OPENAI_ENDPOINT_EMBEDDING: str = os.getenv("AZURE_OPENAI_ENDPOINT_EMBEDDING")
    AZURE_OPENAI_DEPLOYMENT_EMBEDDING: str = os.getenv("AZURE_OPENAI_DEPLOYMENT_EMBEDDING")
    AZURE_OPENAI_API_VERSION_EMBEDDING: str = os.getenv("AZURE_OPENAI_API_VERSION_EMBEDDING")
    CHROMA_DB_DIR: str = "/app/data/chroma"
    COLLECTION_NAME: str = "agent_docs"
    RERANKER_MODEL: str = "ms-marco-MiniLM-L-12-v2" 
    
    
    model_config = SettingsConfigDict(
        env_file=".env",      
        env_file_encoding="utf-8",
        extra="ignore"        
    )
    

settings = Settings()