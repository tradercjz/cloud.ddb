# FILE: ./debug_sdk_direct_call.py

import asyncio
import os
from dotenv import load_dotenv

# --- 阿里云 SDK Imports ---
from alibabacloud_eci20180808.client import Client as EciClient
# 不再需要 eci_models
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_openapi_util.client import Client as OpenApiUtilClient # 引入这个工具类
import aiohttp

# -----------------------------------------------------------------------------
# 1. 配置区域
# -----------------------------------------------------------------------------
load_dotenv()
REGION_ID = os.getenv("ALIYUN_REGION_ID")
ACCESS_KEY_ID = os.getenv("ALIYUN_ACCESS_KEY_ID")
ACCESS_KEY_SECRET = os.getenv("ALIYUN_ACCESS_KEY_SECRET")

CONTAINER_GROUP_ID = "eci-bp1etbkiytfv88zpvxiu" 
CONTAINER_NAME = "code-server-container"

async def main():
    print("--- Ultimate SDK Call Sanity Check (Direct Dictionary Method) ---")
    if not all([ACCESS_KEY_ID, ACCESS_KEY_SECRET, REGION_ID]):
        print("FATAL: Aliyun credentials or region not found in .env file. Exiting.")
        return

    # --- 关键修复：完整地创建 config 对象 ---
    print(f"Creating Aliyun client for region: {REGION_ID}")
    config = open_api_models.Config(
        access_key_id=ACCESS_KEY_ID,
        access_key_secret=ACCESS_KEY_SECRET,
        region_id=REGION_ID
    )
    # 必须手动设置 endpoint
    config.endpoint = f'eci.{REGION_ID}.aliyuncs.com'
    
    client = EciClient(config)
    print("Aliyun ECI Client created successfully.")

    # 2. 手动构建 query 字典
    command_list = ["ls", "-l", "/"]
    
    # 阿里云API规定 Command 参数必须是 JSON 字符串格式
    import json
    command_str = json.dumps(command_list)
    
    query = {
        "RegionId": REGION_ID,
        "ContainerGroupId": CONTAINER_GROUP_ID,
        "ContainerName": CONTAINER_NAME,
        "Command": command_str # 将 JSON 字符串传递给 Command
    }
    
    # 3. 构建 OpenApiRequest
    req = open_api_models.OpenApiRequest(
        query=OpenApiUtilClient.query(query)
    )
    params = open_api_models.Params(
        action='ExecContainerCommand',
        version='2018-08-08',
        protocol='HTTPS',
        pathname='/',
        method='POST',
        auth_type='AK',
        style='RPC',
        req_body_type='formData',
        body_type='json'
    )
    
    runtime = util_models.RuntimeOptions()

    try:
        print(f"Calling API with direct query dictionary: {query}")
        response_dict = await client.call_api_async(params, req, runtime)
        
        print("✅ Aliyun API call SUCCEEDED (raw dictionary response).")
        
        websocket_uri = response_dict.get('body', {}).get('WebSocketUri')
        print(f"WebSocket URI: {websocket_uri}")

        if websocket_uri:
            print("Connecting to WebSocket to get command output...")
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri, timeout=30) as ws:
                    print("WebSocket connected. Output from 'ls -l /':")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            print(msg.data[1:].decode('utf-8', errors='ignore'), end='')
            print("\n\n--- TEST PASSED ---")
        
    except Exception as e:
        print("\n❌ --- TEST FAILED ---")
        print(f"An exception occurred during the direct API call:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())