import asyncio
import os
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# 重要：确保此脚本能找到 core 和 services 模块。
# 如果您的项目根目录不在 Python 路径中，可能需要添加以下代码：
# import sys
# sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# ---------------------------------------------------------------------------

# 1. 在导入任何自定义模块之前，首先加载环境变量
print("--- Loading environment variables from .env file ---")
load_dotenv()

# 2. 现在可以安全地导入依赖环境变量的服务了
from services.graph_rag_service import GraphRAGService

# --- 测试配置 ---
QUERIES_TO_TEST = [
    "dolphindb的分布式计算原理是什么？",
    "如何定义全局变量",  # 用于测试API如何处理
]

async def main():
    """
    主异步函数，用于执行对 GraphRAGService 的测试。
    """
    print("\n--- Initializing GraphRAGService ---")
    
    # 3. 实例化服务
    # 它会自动从环境变量中读取配置
    rag_service = GraphRAGService()

    # 检查服务是否已正确配置
    if not rag_service.api_url or not rag_service.api_key:
        print("\n❌ FATAL ERROR: Graph RAG service is not configured.")
        print("Please ensure GRAPH_RAG_API_URL and GRAPH_RAG_API_KEY are set in your .env file.")
        return

    print(f"Service configured for API URL: {rag_service.api_url}")
    print("-" * 40)

    # 4. 遍历并执行测试用例
    for i, query in enumerate(QUERIES_TO_TEST, 1):
        print(f"\n>>> Test Case #{i}: Sending query...")
        print(f"    Query: '{query}'")
        
        # 调用服务的 query 方法
        result = await rag_service.query(query)
        
        print(f"<<< Test Case #{i}: Received response:")
        print("-" * 20)
        
        # 5. 打印结果
        if result and not result.startswith("Error:"):
            print("✅ SUCCESS: The service returned a context string.")
            print("--- Context Snippet (first 500 characters) ---")
            print(result[:500] + "..." if len(result) > 500 else result)
            print("-" * (len("--- Context Snippet (first 500 characters) ---")))
        elif result:
            print(f"⚠️  SERVICE RETURNED AN ERROR: {result}")
        else:
            print("❌ FAILED: The service returned None, indicating a major issue.")
        
        print("-" * 40)

if __name__ == "__main__":
    # 使用 asyncio.run 来执行异步的 main 函数
    print("--- Starting Graph RAG Service Standalone Test ---")
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\nAn unexpected error occurred during the test run: {e}")