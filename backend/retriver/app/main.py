
from typing import List
from pathlib import Path
from io import BytesIO
import logging

from app.retriver.app.engine import rag_engine
from app.retriver.app.ingestion import load_and_chunk_pdf_path
from app.retriver.app.models import SearchResult, IngestResponse



logger = logging.getLogger(__name__)


def ingest_folder(folder_path: str) -> List[IngestResponse]:
    """
    Ingest all PDF files from a given folder into the RAG index.

    Parameters
    ----------
    folder_path : str
        Path to the folder containing PDF files

    Returns
    -------
    List[IngestResponse]
        One response per PDF file
    """
    folder = Path(folder_path)
    
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    responses: List[IngestResponse] = []

    for pdf_path in folder.iterdir():
        if not pdf_path.is_file() or pdf_path.suffix.lower() != ".pdf":
            continue
        print('i am here',pdf_path)
        try:
            
            try:
                chunks = load_and_chunk_pdf_path(
                    path=pdf_path
                )
            except Exception as error:
                
                print(error)

            if chunks:
                rag_engine.ingest_documents(chunks)
                responses.append(
                    IngestResponse(
                        filename=pdf_path.name,
                        chunks_added=len(chunks),
                        message="Ingestion successful"
                    )
                )
            else:
                responses.append(
                    IngestResponse(
                        filename=pdf_path.name,
                        chunks_added=0,
                        message="No chunks generated"
                    )
                )

        except Exception as e:
            logger.exception(f"Ingestion failed for {pdf_path.name}: {e}")
            responses.append(
                IngestResponse(
                    filename=pdf_path.name,
                    chunks_added=0,
                    message=f"Ingestion failed: {e}"
                )
            )

    return responses


def retrieve(query: str, k: int = 5) -> List[SearchResult]:
    """
    Retrieve top-k relevant documents from the RAG index.

    Parameters
    ----------
    query : str
        Query string
    k : int
        Number of results

    Returns
    -------
    List[SearchResult]
    """
    if not query or not query.strip():
        raise ValueError("Query must be non-empty")
    if k < 1:
        raise ValueError("k must be >= 1")

    docs = rag_engine.search(query, k)
    results: List[SearchResult] = []

    for doc in docs:
        metadata = getattr(doc, "metadata", {}) or {}
        score = metadata.get("relevance_score")

        content = getattr(doc, "page_content", None)
        if content is None:
            content = getattr(doc, "content", "")

        results.append(
            SearchResult(
                content=content,
                metadata=metadata,
                score=score
            )
        )

    return results



