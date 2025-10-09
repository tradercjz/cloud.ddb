# FILE: ./test_write_file_tool.py

import asyncio
from dotenv import load_dotenv
import os
from concurrent.futures import ThreadPoolExecutor

# --- 关键：首先加载环境变量 ---
# 这会加载 .env 文件，让后续的 aiyun_service 和数据库连接能获取到凭证
load_dotenv()

# --- 引入我们需要测试的组件和依赖 ---
from agent.execution_result import ExecutionResult
from db.session import SessionLocal
from db import crud
from agent.tools.file_tools import WriteFileTool, WriteFileInput # 引入重构后的工具和输入模型

# --- 测试参数 ---
# !!! 请将这里的 env_id 替换为您要测试的、正在运行的环境的 ID !!!
TEST_ENV_ID = "ddb-env-b3008f5f" # <--- 修改这里

# --- 定义测试用例 ---
test_cases = [
    {
        "name": "Simple Text File Creation",
        "input": {
            "file_path": "ai_test_simple.txt",
            "content": "Hello from the final, working test script!"
        }
    }
]

async def run_test():
    """
    主测试函数, 用于协调和运行所有测试。
    """
    print("--- Starting WriteFileTool Standalone Test (Final, Corrected Version) ---")
    
    main_loop = asyncio.get_running_loop()
    print(f"Main event loop ID: {id(main_loop)}")
    
    # ... (从数据库获取 env 的逻辑不变)
    db = SessionLocal()
    try:
        env = await crud.get_environment(db, env_id=TEST_ENV_ID)
    finally:
        await db.close()
    
    if not env:
        print(f"FATAL: Environment with ID '{TEST_ENV_ID}' not found.")
        return
    # ...

    # 实例化 WriteFileTool，传递主事件循环
    write_tool = WriteFileTool(
        region_id=env.region_id,
        container_group_id=env.code_server_group_id,
        main_event_loop=main_loop
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        for i, case in enumerate(test_cases, 1):
            print(f"\n--- Running Test Case #{i}: {case['name']} ---")
            
            tool_input = WriteFileInput(**case['input'])
            
            # --- 关键修复：直接提交 run 方法，不使用 next() 或 lambda ---
            future = executor.submit(write_tool.run, tool_input)
            
            # 阻塞等待线程完成，并获取 run 方法返回的 ExecutionResult 对象
            result = future.result() 

            print(f"Execution Result for Test Case #{i}:")
            if result and isinstance(result, ExecutionResult):
                if result.success:
                    print(f"✅ SUCCESS: {result.data}")
                else:
                    print(f"❌ FAILED: {result.error_message}")
            else:
                print(f"❌ FAILED: Tool did not return a valid ExecutionResult. Got: {type(result)}")
    
    print("\n--- All Tests Finished ---")
    print(f"Please manually check the code-server UI for env '{TEST_ENV_ID}' to verify.")

if __name__ == "__main__":
    try:
        asyncio.run(run_test())
    except Exception as e:
        import traceback
        print(f"\nAn error occurred during the test run: {type(e).__name__}: {e}")
        traceback.print_exc()