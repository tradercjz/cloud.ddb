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

# 从您的代码中提取Jina API的逻辑
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
    

class JinaAgent:
    def __init__(self):
        faiss_index_path = "my_docs_advanced.index"
        chunks_mapping_path = "my_docs_chunks_advanced.pkl"
        self.retriever = JinaFaissRetriever(
            index_path=faiss_index_path,
            chunks_path=chunks_mapping_path,
            api_key='jina_e1105e8b8bff4ce4a23a9e3f66c7e501Hlb4KoyuCxtFSSM1QcE2yBAdLWVP'
        )
        
    @llm.prompt() # Or any powerful model you prefer for generation
    def _generate_answer_with_context(self, user_query: str, context_str: str) -> str:
        """
        You are an expert DolphinDB assistant. Your task is to answer the user's query based *only* on the provided context.
        If the context does not contain the answer, state that you cannot find the information in the provided documents.
        Be concise, accurate, and provide code examples if they are present in the context.

        Here is the relevant context retrieved from the knowledge base:
        --- CONTEXT ---
        {{ context_str }}
        --- END CONTEXT ---

        User's Query:
        {{ user_query }}

        Your Answer:
        """
        pass

    def retrieve_and_generate(self, query: str, top_k: int = 5) -> Generator[Any, None, Any]:
        """
        The main entry point for the new RAG workflow.
        1. Retrieves context using the Jina/Faiss retriever.
        2. Generates a final answer using an LLM.
        """
        if not self.retriever:
            yield RagError(message="Retriever is not initialized. Cannot process query.")
            return

        yield RagStart(message="🚀 Starting retrieval with Jina/Faiss...")

        # --- STAGE 1: RETRIEVAL ---
        # The entire retrieval process is now a single, clean method call.
        retrieved_docs: List[Document] = self.retriever.retrieve(query, top_k=top_k)
        
        if not retrieved_docs:
            yield RagEnd(message="No relevant documents found in the knowledge base.", final_document_count=0)
            # We can either stop here or still try to answer without context. Let's stop.
            return "I could not find any relevant information in the knowledge base to answer your question."

        yield RagEnd(message=f"Retrieval complete. Found {len(retrieved_docs)} relevant documents.", final_document_count=len(retrieved_docs))
        
        # --- STAGE 2: GENERATION ---
        # We format the retrieved documents into a single string for the LLM prompt.
        context_parts = []
        for i, doc in enumerate(retrieved_docs):
            context_parts.append(f"--- Document {i+1} (Source: {doc.file_path}) ---\n{doc.source_code}")
        
        context_string = "\n\n".join(context_parts)
        
        # Call the LLM to generate the final answer based on the context.
        # The llm.prompt decorator will handle streaming for us if the UI needs it.
        answer_generator = self._generate_answer_with_context(
            user_query=query,
            context_str=context_string
        )
        
        # Yield all parts from the answer generator (e.g., StreamChunk)
        final_response = None
        try:
            while True:
                part = next(answer_generator)
                yield part # Pass through StreamChunk, etc. to the caller
        except StopIteration as e:
            final_response = e.value
        
        return final_response
    
    
    
def interactive_search():
    """交互式搜索模式"""
    print("=== 知识库交互式搜索 ===")
    print("输入 'quit' 或 'exit' 退出")
    
    jina_agent = JinaAgent()
    
    while True:
        try:
            query = input("\n请输入搜索查询: ").strip()
            if query.lower() in ['quit', 'exit', '退出']:
                print("再见！")
                break
            
            if not query:
                print("请输入有效的查询内容")
                continue
            
            k = input("返回结果数量 (默3): ").strip()
            try:
                k = int(k) if k else 3
            except ValueError:
                k = 3
                print("使用默认值 k=3")
            
            # 1. 创建生成器
            response_generator = jina_agent.retrieve_and_generate(query, k)
            
            # 2. 循环消费生成器并处理其产出
            print("\n--- Agent 响应 ---")
            final_result = None
            full_content = ""
            for item in response_generator:
                # 我们可以根据 item 的类型来决定如何打印
                if isinstance(item, (RagStart, RagEnd, RagError)):
                    # 打印状态更新
                    print(f"[STATUS] {item.message}")
                elif isinstance(item, StreamChunk) and item.type == 'content':
                    # 如果是流式内容，实时打印到控制台
                    print(item.data, end="", flush=True)
                    full_content += item.data
                elif isinstance(item, LLMResponse):
                    # 当生成器结束时，它会返回一个LLMResponse对象
                    final_result = item
            
            print("\n" + "-"*20) # 在流式输出结束后打印一个分隔符

            if final_result:
                if final_result.success:
                    print("\n[INFO] 任务成功完成。")
                    # 如果不是流式输出，最终内容在final_result.content里
                    # 在我们的例子中，流式输出已经打印过了
                else:
                    print(f"\n[ERROR] 任务失败: {final_result.error_message}")
            elif isinstance(response_generator, str): # Handle the case where retriever returns a string directly
                print(response_generator)
            else:
                print("\n[INFO] 未找到相关结果或任务未返回明确结果。")
            
            
            
        except KeyboardInterrupt:
            print("\n\n程序被中断，再见！")
            break
        except Exception as e:
            print(f"发生未知错误: {e}")

if __name__ == "__main__":
    # 可以选择单次搜索或交互式搜索
    
    # 方式1: 单次搜索
    # print("=== 单次搜索模式 ===")
    # user_query = "failed to open chunks怎么处理"
    # results = search_knowledge_base(user_query, k=2)
    
    # 方式2: 交互式搜索 (取消注释下面的行来启用)
    interactive_search()