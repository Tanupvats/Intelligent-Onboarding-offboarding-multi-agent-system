from pydantic import BaseModel
from typing import List, Optional

class SearchRequest(BaseModel):
    query: str
    k: int = 5 

class SearchResult(BaseModel):
    content: str
    metadata: dict
    score: Optional[float] = None

class IngestResponse(BaseModel):
    filename: str
    chunks_added: int
    message: str