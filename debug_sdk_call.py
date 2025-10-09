# FILE: ./debug_sdk_call.py

import asyncio
import os
from dotenv import load_dotenv

# --- 阿里云 SDK Imports ---
from alibabacloud_eci20180808.client import Client as EciClient
from alibabacloud_eci20180808 import models as eci_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
import aiohttp

# -----------------------------------------------------------------------------
# 1. 配置区域
# -----------------------------------------------------------------------------
load_dotenv()
REGION_ID = os.getenv("ALIYUN_REGION_ID")
ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID")
ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")

# !!! 请确保这里的配置与您要测试的环境完全一致 !!!
CONTAINER_GROUP_ID = "eci-bp19jc3yztavttkor0p0" 
CONTAINER_NAME = "code-server-container"

async def main():
    print("--- Ultimate SDK Call Sanity Check ---")
    if not all([ACCESS_KEY_ID, ACCESS_KEY_SECRET, REGION_ID]):
        print("FATAL: Aliyun credentials or region not found in .env file. Exiting.")
        return

    # 1. 创建客户端
    config = open_api_models.Config(
        access_key_id=ACCESS_KEY_ID,
        access_key_secret=ACCESS_KEY_SECRET,
        region_id=REGION_ID
    )
    config.endpoint = f'eci.{REGION_ID}.aliyuncs.com'
    client = EciClient(config)
    print("Aliyun ECI Client created.")

    # 2. 创建最简单的请求对象
    request = eci_models.ExecContainerCommandRequest()
    request.region_id = REGION_ID
    request.container_group_id = CONTAINER_GROUP_ID
    request.container_name = CONTAINER_NAME
    request.command = ["ls", "-l", "/"] # 最简单、最不可能出错的命令

    runtime = util_models.RuntimeOptions()

    try:
        print(f"Calling API with request object: {request.to_map()}")
        exec_response = await client.exec_container_command_with_options_async(request, runtime)
        print("✅ Aliyun API call SUCCEEDED.")
        
        websocket_uri = exec_response.body.web_socket_uri
        print(f"WebSocket URI: {websocket_uri}")

        # 如果成功，尝试连接WebSocket获取输出
        if websocket_uri:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri, timeout=30) as ws:
                    print("WebSocket connected. Output from 'ls -l /':")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            print(msg.data[1:].decode('utf-8', errors='ignore'), end='')
            print("\n--- TEST PASSED ---")
        
    except Exception as e:
        print("\n❌ --- TEST FAILED ---")
        print(f"An exception occurred during the most basic API call:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())