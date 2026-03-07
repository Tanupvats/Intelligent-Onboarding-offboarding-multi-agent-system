import logging
from langchain_openai import OpenAIEmbeddings,AzureOpenAIEmbeddings
from langchain_chroma import Chroma
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever, ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from app.retriver.app.config import settings

logger = logging.getLogger("uvicorn")

class RAGService:
    def __init__(self):
        
        self.embeddings = AzureOpenAIEmbeddings(
            azure_deployment=settings.AZURE_OPENAI_DEPLOYMENT_EMBEDDING,  
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT_EMBEDDING,
            api_key=settings.AZURE_OPENAI_API_KEY_EMBEDDING
        )

        self.vector_store = Chroma(
            persist_directory=settings.CHROMA_DB_DIR,
            embedding_function=self.embeddings,
            collection_name=settings.COLLECTION_NAME
        )
        self.bm25_retriever = None
        self.pipeline = None
        
        
        self._rebuild_pipeline()

    def _rebuild_pipeline(self):
        """
        Rebuilds the hybrid search (Vector + BM25) and Reranker.
        Must be called after ingestion to update BM25 indices.
        """
        try:
            
            
            existing_docs = self.vector_store.get()['documents']
            
            if not existing_docs:
                logger.warning("Vector Store is empty. Waiting for ingestion.")
                return

            
            all_docs = self.vector_store.as_retriever(search_kwargs={"k": 10000}).invoke(" ")
            
            if not all_docs:
                return

            logger.info(f"Building BM25 index with {len(all_docs)} documents...")
            self.bm25_retriever = BM25Retriever.from_documents(all_docs)
            self.bm25_retriever.k = 5
            
            vector_retriever = self.vector_store.as_retriever(search_kwargs={"k": 5})
            
           
            ensemble_retriever = EnsembleRetriever(
                retrievers=[self.bm25_retriever, vector_retriever],
                weights=[0.5, 0.5]
            )
            
            
            compressor = FlashrankRerank(model=settings.RERANKER_MODEL)
            self.pipeline = ContextualCompressionRetriever(
                base_compressor=compressor,
                base_retriever=ensemble_retriever
            )
            logger.info("RAG Pipeline successfully built.")
            
        except Exception as e:
            logger.error(f"Failed to build pipeline: {e}")

    def ingest_documents(self, chunks: list):
        """Add documents to VectorDB and refresh pipeline"""
        if not chunks:
            return
            
        self.vector_store.add_documents(chunks)
        
        self._rebuild_pipeline()

    def search(self, query: str, k: int = 5):
        if not self.pipeline:
            return []
        
        docs = self.pipeline.invoke(query)
        return docs[:k] 


rag_engine = RAGService()