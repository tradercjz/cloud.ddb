# FILE: ./debug_write_file.py

import asyncio
import os
import sys
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Tuple, List

from dotenv import load_dotenv

# --- 阿里云 SDK Imports ---
from alibabacloud_eci20180808.client import Client as EciClient
from alibabacloud_eci20180808 import models as eci_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
import aiohttp
import shlex

# -----------------------------------------------------------------------------
# 1. 配置区域
# -----------------------------------------------------------------------------
load_dotenv()
REGION_ID = os.getenv("ALIYUN_REGION_ID")
ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID")
ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")

# !!! 请确保这里的配置与您要测试的环境完全一致 !!!
CONTAINER_GROUP_ID = "eci-bp19jc3yztavttkor0p0" # 替换为您的 code-server ECI ID
CONTAINER_NAME = "code-server-container"       # 确认容器名称是否正确

# --- 测试用例 ---
FILE_PATH = "final_test.py"
FILE_CONTENT = "print('This is the final test and it must work.')"

# -----------------------------------------------------------------------------
# 2. 核心功能的自包含实现 (严格模拟 SDK 范式)
# -----------------------------------------------------------------------------

class AliyunECIExecutor:
    """一个独立的、严格遵循 Tea SDK 范式的 ECI 执行器"""

    def __init__(self, region_id, access_key_id, access_key_secret):
        self.region_id = region_id
        self.client = self._create_client(access_key_id, access_key_secret)
        print("AliyunECIExecutor initialized.")

    def _create_client(self, access_key_id, access_key_secret) -> EciClient:
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            region_id=self.region_id
        )
        config.endpoint = f'eci.{self.region_id}.aliyuncs.com'
        return EciClient(config)

    async def execute_command_in_container(self, container_group_id: str, container_name: str, command_list: List[str]) -> Tuple[bool, str]:
        print(f"\n[ASYNC TASK] Preparing to execute command list: {command_list}")

        # --- 核心修复 1: 严格按照 TeaModel 的方式创建和填充请求对象 ---
        request = eci_models.ExecContainerCommandRequest()
        request.region_id = self.region_id
        request.container_group_id = container_group_id
        request.container_name = container_name
        request.command = command_list # 直接传递列表
        
        runtime = util_models.RuntimeOptions()

        try:
            print(f"[ASYNC TASK] Calling Aliyun API with request object: {request.to_map()}")
            exec_response = await self.client.exec_container_command_with_options_async(request, runtime)
            print("[ASYNC TASK] Aliyun API call finished successfully.")
            
            websocket_uri = exec_response.body.web_socket_uri
            if not websocket_uri:
                return False, "API response did not contain a WebSocket URI."
            
            # ... 后续的 WebSocket 连接逻辑保持不变 ...
            print(f"[ASYNC TASK] Got WebSocket URI, connecting via aiohttp...")
            output_buffer = []
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri, timeout=30) as ws:
                    print("[ASYNC TASK] WebSocket connected. Receiving data...")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            output_buffer.append(msg.data[1:].decode('utf-8', errors='ignore'))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            return False, f"Exec WebSocket connection error: {ws.exception()}"
            
            full_output = "".join(output_buffer)
            print(f"[ASYNC TASK] WebSocket closed. Full output received: {repr(full_output)}")
            return True, full_output

        except Exception as e:
            print(f"[ASYNC TASK] An exception occurred during API call: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False, str(e)


def run_file_write_in_thread(
    main_loop, 
    region_id, access_key_id, access_key_secret, 
    container_group_id, container_name, 
    file_path, content
):
    print(f"\n[WORKER THREAD] Thread started.")
    
    # --- 核心修复 2: 构建原生命令列表，而不是 shell 字符串 ---
    # 我们将使用 /bin/sh -c '...' 的方式，这是最可靠的。
    # `shlex.quote` 依然是处理单引号和特殊字符的最佳方式。
    dir_path = os.path.dirname(file_path)
    command_str = ""
    if dir_path:
        command_str += f"mkdir -p {shlex.quote(dir_path)} && "
    command_str += f"echo {shlex.quote(content)} > {shlex.quote(file_path)} && echo WRITE_SUCCESS"
    
    # 最终传递给 API 的命令列表
    command_list_for_api = ["/bin/sh", "-c", command_str]
    
    print(f"[WORKER THREAD] Prepared command list for API: {command_list_for_api}")

    try:
        executor = AliyunECIExecutor(region_id, access_key_id, access_key_secret)
        coro = executor.execute_command_in_container(container_group_id, container_name, command_list_for_api)
        
        future: Future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        
        print("[WORKER THREAD] Waiting for future.result()...")
        success, output = future.result(timeout=60)
        print(f"[WORKER THREAD] future.result() completed. Success: {success}")
        
        if success and "WRITE_SUCCESS" in output:
            return True, f"Successfully wrote to {file_path}"
        elif success:
            return False, f"Command may have failed (no success marker). Output: {repr(output)}"
        else:
            return False, f"API call failed. Details: {output}"

    except Exception as e:
        print(f"[WORK-THREAD] An exception occurred in the thread: {type(e).__name__}: {e}")
        return False, str(e)

# -----------------------------------------------------------------------------
# 3. 主执行逻辑
# -----------------------------------------------------------------------------

async def main():
    print("--- Independent ECI Exec Debug Script (Strict SDK Model) ---")
    if not all([ACCESS_KEY_ID, ACCESS_KEY_SECRET, REGION_ID]):
        print("FATAL: Aliyun credentials or region not found in .env file. Exiting.")
        return

    main_loop = asyncio.get_running_loop()
    print(f"[MAIN THREAD] Main event loop ID: {id(main_loop)}")

    with ThreadPoolExecutor(max_workers=1) as executor:
        result_future = main_loop.run_in_executor(
            executor,
            run_file_write_in_thread,
            main_loop,
            REGION_ID, ACCESS_KEY_ID, ACCESS_KEY_SECRET,
            CONTAINER_GROUP_ID, CONTAINER_NAME,
            FILE_PATH, FILE_CONTENT
        )
        
        print("[MAIN THREAD] Waiting for the worker thread to finish...")
        final_success, final_output = await result_future
        print("\n--- TEST SUMMARY ---")
        print(f"Success: {final_success}")
        print(f"Output: {final_output}")
        print("--------------------")

if __name__ == "__main__":
    if sys.version_info >= (3, 7):
        asyncio.run(main())
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())