# FILE: ./agent/tools/file_tools.py

import os
import shlex
import asyncio
import json
import base64
from concurrent.futures import Future
from typing import Tuple, List, Generator, Any

from pydantic import Field

from agent.tools.tool_interface import BaseTool, ToolInput, ExecutionResult # <-- MODIFY: REMOVE ensure_generator
from core.config import settings

from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_eci20180808.client import Client as EciClient
from alibabacloud_tea_util import models as util_models
from alibabacloud_openapi_util.client import Client as OpenApiUtilClient
import aiohttp


class WriteFileInput(ToolInput):
    file_path: str = Field(description="The relative path to the file in the workspace.")
    content: str = Field(description="The full content to be written to the file.")

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Creates or overwrites a file in the workspace with the provided content. Can handle large files."
    args_schema = WriteFileInput

    def __init__(
        self, 
        region_id: str, 
        container_group_id: str, 
        main_event_loop: asyncio.AbstractEventLoop, 
        container_name: str = "code-server-container"
    ):
        self.region_id = region_id
        self.container_group_id = container_group_id
        self.container_name = container_name
        self.main_loop = main_event_loop
        self.aliyun_client = self._create_aliyun_client(region_id)
        # Use a much smaller chunk size, as it's now just the data, not the whole command.
        self.CHUNK_SIZE = 1800 

    def _create_aliyun_client(self, region_id: str) -> EciClient:
        config = open_api_models.Config(
            access_key_id=settings.ALIYUN_ACCESS_KEY_ID,
            access_key_secret=settings.ALIYUN_ACCESS_KEY_SECRET,
            region_id=region_id
        )
        config.endpoint = f'eci.{region_id}.aliyuncs.com'
        return EciClient(config)

    async def _execute_single_command_async(self, command_str: str) -> Tuple[bool, str]:
        """
        Executes a single, self-contained shell command string asynchronously.
        This is now the core async function that gets called for each step.
        """
        command_list_for_api = ["/bin/sh", "-c", command_str]
        command_json = json.dumps(command_list_for_api)

        query = {
            "RegionId": self.region_id,
            "ContainerGroupId": self.container_group_id,
            "ContainerName": self.container_name,
            "Command": command_json
        }
        req = open_api_models.OpenApiRequest(query=OpenApiUtilClient.query(query))
        params = open_api_models.Params(
            action='ExecContainerCommand', version='2018-08-08', protocol='HTTPS',
            pathname='/', method='POST', auth_type='AK', style='RPC',
            req_body_type='formData', body_type='json'
        )
        runtime = util_models.RuntimeOptions()

        try:
            response_dict = await self.aliyun_client.call_api_async(params, req, runtime)
            websocket_uri = response_dict.get('body', {}).get('WebSocketUri')
            if not websocket_uri: return False, "API response did not contain a WebSocket URI."
            
            output_buffer = []
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri, timeout=30) as ws:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            output_buffer.append(msg.data[1:].decode('utf-8', errors='ignore'))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            return False, f"Exec WebSocket connection error: {ws.exception()}"
            
            full_output = "".join(output_buffer)
            return True, full_output
        except Exception as e:
            return False, f"API call failed: {str(e)}"

    async def _run_async(self, args: WriteFileInput) -> ExecutionResult:
        """
        The new async orchestrator for the multi-step write process.
        """
        dir_path = os.path.dirname(args.file_path)
        if dir_path:
            mkdir_success, mkdir_output = await self._execute_single_command_async(f"mkdir -p {shlex.quote(dir_path)}")
            if not mkdir_success:
                return ExecutionResult(success=False, error_message=f"Failed to create directory: {mkdir_output}")

        if not args.content:
            success, output = await self._execute_single_command_async(f"echo -n '' > {shlex.quote(args.file_path)}")
            if success:
                return ExecutionResult(success=True, data=f"Successfully wrote empty file to {args.file_path}.")
            else:
                return ExecutionResult(success=False, error_message=f"Failed to write empty file: {output}")

        encoded_content = base64.b64encode(args.content.encode('utf-8')).decode('ascii')
        chunks = [encoded_content[i:i + self.CHUNK_SIZE] for i in range(0, len(encoded_content), self.CHUNK_SIZE)]
        
        tmp_file_path = f"{args.file_path}.b64.tmp"

        # Step 1: Write first chunk
        first_chunk_cmd = f"echo -n {shlex.quote(chunks[0])} > {shlex.quote(tmp_file_path)}"
        success, output = await self._execute_single_command_async(first_chunk_cmd)
        if not success:
            return ExecutionResult(success=False, error_message=f"Failed on first chunk write: {output}")

        # Step 2: Append subsequent chunks
        for i, chunk in enumerate(chunks[1:]):
            append_cmd = f"echo -n {shlex.quote(chunk)} >> {shlex.quote(tmp_file_path)}"
            success, output = await self._execute_single_command_async(append_cmd)
            if not success:
                return ExecutionResult(success=False, error_message=f"Failed on chunk append #{i+2}: {output}")

        # Step 3: Decode and cleanup
        final_cmd = (
            f"base64 -d {shlex.quote(tmp_file_path)} > {shlex.quote(args.file_path)} && "
            f"rm {shlex.quote(tmp_file_path)} && "
            "echo WRITE_SUCCESS"
        )
        success, output = await self._execute_single_command_async(final_cmd)
        
        if success and "WRITE_SUCCESS" in output:
            return ExecutionResult(success=True, data=f"Successfully wrote {len(args.content)} bytes to {args.file_path}.")
        else:
            return ExecutionResult(success=False, error_message=f"Failed on final decode/cleanup step. Output: {output}")

    # The public 'run' method now handles the thread-to-async transition.
    def run(self, args: WriteFileInput) -> Generator[Any, None, ExecutionResult]:
        """
        Executes the file write operation.
        This is a synchronous wrapper that runs the async logic in the main event loop.
        """
        # We don't yield from this method anymore, so we don't need a generator.
        # However, the ToolManager expects a generator, so we wrap the result.
        
        coro = self._run_async(args)
        future: Future = asyncio.run_coroutine_threadsafe(coro, self.main_loop)
        
        try:
            # Block and wait for the final result from the async orchestrator
            result = future.result(timeout=120) # Increased timeout for multi-step process
            
            # The ToolManager expects a generator, so we wrap the final result.
            def result_generator():
                return result
                yield
            return result_generator()

        except Exception as e:
            error_result = ExecutionResult(
                success=False, 
                error_message=f"Error executing multi-step file write: {type(e).__name__}: {str(e)}"
            )
            def error_generator():
                return error_result
                yield
            return error_generator()