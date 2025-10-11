import aiohttp
from typing import Optional

from core.config import settings

class GraphRAGService:
    """
    A service to interact with the external Light RAG (Graph-based) API.
    """
    def __init__(self):
        self.api_url = settings.GRAPH_RAG_API_URL
        self.api_key = settings.GRAPH_RAG_API_KEY

        if not self.api_url or not self.api_key:
            print("Warning: Graph RAG service is not configured. `GRAPH_RAG_API_URL` and `GRAPH_RAG_API_KEY` must be set in .env")

    async def query(self, text: str) -> Optional[str]:
        """
        Queries the Graph RAG API and returns the context string.
        """
        if not self.api_url or not self.api_key:
            return "Error: Graph RAG service is not configured."

        headers = {
            "accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
        }
        
        data_payload = {
            "query": text,
            "mode": "hybrid",   
            "only_need_context": True,
            "only_need_prompt": False,
            "response_type": "Multiple Paragraphs",
            "top_k": 40,
            "chunk_top_k": 20,
            "max_entity_tokens": 6000,
            "max_relation_tokens": 8000,
            "max_total_tokens": 30000,
            "enable_rerank": True,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url, json=data_payload, headers=headers, timeout=120
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("response")
                    else:
                        error_text = await response.text()
                        print(f"Graph RAG API Error: HTTP {response.status}: {error_text}")
                        return f"Error: Failed to query Graph RAG service. Status: {response.status}"
        except Exception as e:
            print(f"An exception occurred while querying Graph RAG service: {e}")
            return f"Error: An exception occurred while contacting the Graph RAG service: {str(e)}"

# 创建一个单例供应用全局使用
graph_rag_service = GraphRAGService()