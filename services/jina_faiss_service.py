# file: ./rag/jina_faiss_retriever.py

import os
import faiss
import numpy as np
import pickle
import json
import requests
from typing import Generator, List, Dict, Any, Optional
from llm.llm_client import LLMResponse, StreamChunk
from llm.llm_prompt import llm

from context.pruner import Document
from rag.rag_status import RagEnd, RagError, RagStart # 复用我们已有的Document数据结构

from core.config import settings

class JinaEmbeddingClient:
    """A client to generate embeddings using the Jina AI API."""
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("JINA_API_KEY")
        if not self.api_key:
            raise ValueError("Jina API key not found. Please set the JINA_API_KEY environment variable.")
        self.api_url = 'https://api.jina.ai/v1/embeddings'
        self.model = "jina-embeddings-v4" # 可以将其作为参数

    def get_query_embedding(self, query: str) -> Optional[List[float]]:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        data = {
            "model": self.model,
            "task": "retrieval.query",
            "input": [query]
        }
        try:
            response = requests.post(self.api_url, headers=headers, data=json.dumps(data), timeout=30.0)
            response.raise_for_status()
            result = response.json()
            if 'data' in result and result['data'] and 'embedding' in result['data'][0]:
                return result['data'][0]['embedding']
            else:
                print(f"Error: Unexpected Jina API response format: {result}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Error: Jina API request failed: {e}")
            return None
        except Exception as e:
            print(f"Error: An unexpected error occurred while getting embedding: {e}")
            return None

class JinaFaissRetriever:
    """
    A retriever that uses a pre-built Faiss index and Jina embeddings
    to find the most relevant document chunks.
    """
    def __init__(self, index_path: str, chunks_path: str, api_key: Optional[str] = None):
        self.index_path = index_path
        self.chunks_path = chunks_path
        self.embedding_client = JinaEmbeddingClient(api_key=api_key)
        
        # Load the index and documents upon initialization
        try:
            print(f"Loading Faiss index from {self.index_path}...")
            self.index = faiss.read_index(self.index_path)
            with open(self.chunks_path, 'rb') as f:
                # The chunks are the raw text content
                self.chunks: List[str] = pickle.load(f)
            print(f"Successfully loaded index with {self.index.ntotal} vectors and {len(self.chunks)} chunks.")
        except FileNotFoundError:
            raise RuntimeError(f"Index files not found. Please ensure '{self.index_path}' and '{self.chunks_path}' exist.")
        except Exception as e:
            raise RuntimeError(f"Failed to load Faiss index or chunks: {e}")

    def retrieve(self, query: str, top_k: int = 3) -> List[Document]:
        """
        Retrieves the top_k most relevant document chunks for a given query.
        """
        if not query:
            return []

        # 1. Get query embedding
        print(f"Generating embedding for query: '{query}'")
        query_embedding = self.embedding_client.get_query_embedding(query)
        if query_embedding is None:
            print("Failed to generate query embedding. Cannot retrieve.")
            return []
        
        print("Query embedding generated successfully.")

        # 2. Prepare for Faiss search
        query_vector_np = np.array([query_embedding], dtype='float32')
        if query_vector_np.shape[1] != self.index.d:
            print(f"Error: Query vector dimension ({query_vector_np.shape[1]}) does not match index dimension ({self.index.d}).")
            return []
            
        # 3. Perform Faiss search
        print(f"Searching index for top {top_k} results...")
        distances, indices = self.index.search(query_vector_np, top_k)
        
        # 4. Format results into our standard `Document` objects
        results: List[Document] = []
        for i, idx in enumerate(indices[0]):
            if idx != -1 and idx < len(self.chunks):
                # We create a Document object for consistency with the rest of the framework.
                # The file_path is synthetic, indicating the source and chunk index.
                source_path = f"faiss_chunk_{idx}"
                content = self.chunks[idx]
                
                # We can add distance to metadata for more advanced logic later
                metadata = {
                    "source": "faiss_db",
                    "chunk_index": int(idx),
                    "distance": float(distances[0][i])
                }
                
                # We're creating Document objects, not RetrievalResult, to match DDBRAG's expected type
                # For `score` we convert distance to similarity
                results.append(Document(
                    file_path=source_path, 
                    source_code=content, # Using source_code field for content
                    tokens=len(content) # A rough estimate
                ))
        
        print(f"Retrieval complete. Found {len(results)} relevant documents.")
        return results
    

class JinaFaissService:
    """
    A singleton service that encapsulates the JinaFaissRetriever.
    It initializes the retriever upon application startup.
    """
    def __init__(self):
        self.retriever: Optional[JinaFaissRetriever] = None
        self.is_initialized = False

        try:
            # 从 settings 中读取路径和 API Key
            index_path = settings.FAISS_INDEX_PATH
            chunks_path = settings.FAISS_CHUNKS_PATH
            api_key = os.getenv("JINA_API_KEY", 'jina_e1105e8b8bff4ce4a23a9e3f66c7e501Hlb4KoyuCxtFSSM1QcE2yBAdLWVP') # 从环境变量读取，并提供硬编码的备用值

            if not os.path.exists(index_path) or not os.path.exists(chunks_path):
                raise FileNotFoundError(f"Index or chunks file not found. Checked paths: '{index_path}', '{chunks_path}'")

            # 实例化您原来的 JinaFaissRetriever
            self.retriever = JinaFaissRetriever(
                index_path=index_path,
                chunks_path=chunks_path,
                api_key=api_key
            )
            self.is_initialized = True
            print("SUCCESS: JinaFaissService initialized successfully.")
                
        except (ValueError, RuntimeError, FileNotFoundError) as e:
            # 捕获所有预期的初始化错误
            print(f"WARNING: JinaFaissService could not initialize. Error: {e}. 'jina' RAG mode will be unavailable.")
        except Exception as e:
            # 捕获其他意外错误
            print(f"WARNING: An unexpected error occurred during JinaFaissService initialization: {e}. 'jina' RAG mode will be unavailable.")

    def retrieve(self, query: str, top_k: int = 5) -> List[Document]:
        """
        Public method to perform retrieval. Delegates the call to the internal retriever instance.
        """
        if not self.is_initialized or not self.retriever:
            print("Error: JinaFaissService is not ready for retrieval.")
            # 返回空列表而不是错误字符串，以保持类型一致性
            return []
        
        # 直接调用您原来的 retrieve 方法
        return self.retriever.retrieve(query, top_k=top_k)
    