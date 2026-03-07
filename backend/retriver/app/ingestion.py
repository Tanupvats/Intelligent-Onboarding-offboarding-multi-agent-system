import os
import tempfile
import logging
from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_experimental.text_splitter import SemanticChunker
from langchain_openai import OpenAIEmbeddings,AzureOpenAIEmbeddings
from pathlib import Path
from app.retriver.app.config import settings

logger = logging.getLogger("uvicorn")


def load_and_chunk_pdf_path(path: str) -> list:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)

    loader = PyPDFLoader(str(path))
    raw_docs = loader.load()

    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_EMBEDDING,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT_EMBEDDING,
        api_key=settings.AZURE_OPENAI_API_KEY_EMBEDDING
        
    )

    splitter = SemanticChunker(embeddings, breakpoint_threshold_type="percentile")
    chunks = splitter.split_documents(raw_docs)
    return chunks

def ingest_folder(folder: str) -> None:
    p = Path(folder)
    for pdf in sorted(p.glob("*.pdf")):
        try:
            chunks = load_and_chunk_pdf_path(str(pdf))
            print(f"{pdf.name}: {len(chunks)} chunks ")
        except Exception as e:
            print(f"{pdf.name}: 0 chunks  {e}")
