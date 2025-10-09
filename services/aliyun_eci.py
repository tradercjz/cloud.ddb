# FILE: services/aliyun_eci.py

import asyncio
import time
from typing import Dict, List, Tuple

import aiohttp

from alibabacloud_eci20180808.client import Client as EciClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_eci20180808 import models as eci_models
from alibabacloud_tea_util import models as util_models

from core.config import settings
from schemas import EnvironmentPublic

class AliyunECIService:
    """
    Service to manage DolphinDB instances on Alibaba Cloud ECI.
    This is the real implementation using the Alibaba Cloud SDK.
    """

    def _create_client(self, region_id: str) -> EciClient:
        """
        Initializes and returns an ECI client for a specific region.
        """
        config = open_api_models.Config(
            access_key_id=settings.ALIYUN_ACCESS_KEY_ID,
            access_key_secret=settings.ALIYUN_ACCESS_KEY_SECRET,
            region_id=region_id
        )
        # The endpoint is region-specific.
        config.endpoint = f'eci.{region_id}.aliyuncs.com'
        return EciClient(config)

    async def create_instance(self, env: EnvironmentPublic) -> Tuple[str, str]:
        """
        Provisions a complete DolphinDB instance on ECI.
        This includes creating the ECI container group with a public IP and a data volume.

        Returns:
            A tuple of (public_ip, container_group_id).
        """
        client = self._create_client(env.region_id)
        print(f"[{env.id}] Starting provisioning on Aliyun ECI in region {env.region_id}...")

        # NOTE: For ECI, we can directly assign an EIP and create a temporary data volume
        # without separate API calls for EIP and Disks, simplifying the process.
        
        container_group_name = f"dolphindb-env-{env.id}"

        # Define the container within the group
        container_definition = eci_models.CreateContainerGroupRequestContainer(
            name="dolphindb-container",
            image=settings.DDB_CONTAINER_IMAGE_URL,
            cpu=env.spec_cpu,
            memory=env.spec_memory,
            # Expose the DolphinDB port
            port=[eci_models.CreateContainerGroupRequestContainerPort(protocol="TCP", port=8848)]
        )

        # Define a temporary data volume. This volume's lifecycle is tied to the ECI.
        # For true persistence across restarts, you would use Aliyun Disks (ESSD).
        # For this on-demand use case, a temporary volume is often sufficient.
        volume_definition = eci_models.CreateContainerGroupRequestVolume(
            name="ddb-data-volume",
            type="EmptyDirVolume" # This creates a temporary directory
        )

        # Create the full container group request object
        create_request = eci_models.CreateContainerGroupRequest(
            region_id=env.region_id,
            container_group_name=container_group_name,
            security_group_id=settings.ALIYUN_SECURITY_GROUP_ID,
            v_switch_id=settings.ALIYUN_VSWITCH_ID,
            auto_create_eip=True,
            eip_bandwidth=200,
            container=[container_definition],
            # volumes=[volume_definition], # Uncomment if you use volumes
            # Add a tag for easy identification and cost tracking
            tag=[eci_models.CreateContainerGroupRequestTag(key="owner_id", value=str(env.owner_id))]
        )

        try:
            print(f"[{env.id}] Sending CreateContainerGroup request to Alibaba Cloud...")
            create_response = await client.create_container_group_with_options_async(create_request, util_models.RuntimeOptions())
            
            container_group_id = create_response.body.container_group_id
            print(f"[{env.id}] ECI instance created with ID: {container_group_id}. Now waiting for it to become 'Running'...")

            # Poll for the instance to be running and get its public IP
            public_ip = await self._wait_for_instance_running(client, container_group_id, env.region_id, env.id)

            print(f"[{env.id}] Provisioning complete. Public IP: {public_ip}")
            return public_ip, container_group_id

        except Exception as error:
            print(f"[{env.id}] FAILED to create ECI instance. Error: {error}")
            # The 'Recommend' field is very useful for debugging
            if hasattr(error, 'data') and error.data.get("Recommend"):
                print(f"[{env.id}] Aliyun Recommend: {error.data.get('Recommend')}")
            raise error # Re-raise the exception to be caught by the worker
        
    async def create_code_server_instance(
        self, 
        env: EnvironmentPublic, 
        dolphindb_host_ip: str
    ) -> Tuple[str, str]:
        """
        Provisions a standalone code-server instance on ECI, injecting the DolphinDB host IP.

        Args:
            env: The environment schema containing metadata.
            dolphindb_host_ip: The public IP of the already created DolphinDB instance.

        Returns:
            A tuple of (public_ip, container_group_id) for the new code-server instance.
        """
        client = self._create_client(env.region_id)
        print(f"[{env.id}] Starting provisioning for Code-Server instance...")

        # 名字要唯一，可以加上 '-cs' 后缀
        container_group_name = f"codeserver-env-{env.id}"

        # 定义 Code Server 容器
        code_server_container = eci_models.CreateContainerGroupRequestContainer(
            name="code-server-container",
            image=settings.CODE_SERVER_CONTAINER_IMAGE_URL, # 确保已在 config.py 中定义
            cpu=2.0,  # 可以给 code-server 分配更多资源
            memory=4.0,
            port=[eci_models.CreateContainerGroupRequestContainerPort(protocol="TCP", port=env.code_server_port)],

            environment_var=[
                eci_models.CreateContainerGroupRequestContainerEnvironmentVar(
                    key="DDB_HOST",
                    value=dolphindb_host_ip
                )
            ]
        )

        create_request = eci_models.CreateContainerGroupRequest(
            region_id=env.region_id,
            container_group_name=container_group_name,
            security_group_id=settings.ALIYUN_SECURITY_GROUP_ID,
            v_switch_id=settings.ALIYUN_VSWITCH_ID,
            auto_create_eip=True,
            eip_bandwidth=200,
            container=[code_server_container],
            tag=[eci_models.CreateContainerGroupRequestTag(key="owner_id", value=str(env.owner_id))]
        )

        try:
            print(f"[{env.id}] Sending CreateContainerGroup request for Code-Server...")
            create_response = await client.create_container_group_with_options_async(create_request, util_models.RuntimeOptions())
            
            container_group_id = create_response.body.container_group_id
            print(f"[{env.id}] Code-Server ECI created with ID: {container_group_id}. Waiting for 'Running' state...")

            public_ip = await self._wait_for_instance_running(client, container_group_id, env.region_id, env.id)

            print(f"[{env.id}] Code-Server provisioning complete. Public IP: {public_ip}")
            return public_ip, container_group_id

        except Exception as error:
            print(f"[{env.id}] FAILED to create Code-Server ECI instance. Error: {error}")
            if hasattr(error, 'data') and error.data.get("Recommend"):
                print(f"[{env.id}] Aliyun Recommend: {error.data.get('Recommend')}")
            raise error

    async def _wait_for_instance_running(self, client: EciClient, container_group_id: str, region_id: str, env_id: str, timeout_seconds: int = 300) -> str:
        """
        Polls the status of a container group until it is 'Running' or a timeout is reached.
        Returns the public IP address.
        """
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            describe_request = eci_models.DescribeContainerGroupsRequest(
                region_id=region_id,
                container_group_ids=str([container_group_id]) # API expects a JSON string array
            )
            
            describe_response = await client.describe_container_groups_with_options_async(describe_request, util_models.RuntimeOptions())
            
            if describe_response.body.container_groups:
                instance = describe_response.body.container_groups[0]
                status = instance.status
                print(f"[{env_id}] Current ECI status: {status}")

                if status == "Running":
                    if not instance.internet_ip:
                        raise Exception("ECI is Running but has no public IP. Check EIP settings.")
                    return instance.internet_ip
                elif status in ["Failed", "Expired"]:
                    raise Exception(f"ECI instance entered a failed state: {status}. Events: {instance.events}")
            
            await asyncio.sleep(10) # Wait 10 seconds between checks

        raise TimeoutError(f"ECI instance {container_group_id} did not become 'Running' within {timeout_seconds} seconds.")
    
    async def describe_instances_batch(self, region_id: str, container_group_ids: List[str]) -> Dict[str, any]:
        """
        Describes a batch of ECI instances and returns a dictionary mapping
        instance_id to the cloud provider's instance object.
        """
        if not container_group_ids:
            return {}
            
        client = self._create_client(region_id)
        describe_request = eci_models.DescribeContainerGroupsRequest(
            region_id=region_id,
            container_group_ids=container_group_ids
        )
        
        try:
            response = await client.describe_container_groups_with_options_async(describe_request, util_models.RuntimeOptions())
            
            # Create a lookup dictionary for easy access
            live_instances = {
                cg.container_group_id: cg 
                for cg in response.body.container_groups
            }
            return live_instances
        except Exception as e:
            print(f"Error describing instances in batch: {e}")
            return {} # On error, return an empty dict


    async def delete_instance(self, container_group_id: str, region_id: str):
        """
        De-provisions a DolphinDB instance by deleting the ECI container group.
        """
        client = self._create_client(region_id)
        print(f"Starting de-provisioning for ECI instance: {container_group_id}...")

        delete_request = eci_models.DeleteContainerGroupRequest(
            region_id=region_id,
            container_group_id=container_group_id
        )

        try:
            await client.delete_container_group_with_options_async(delete_request, util_models.RuntimeOptions())
            print(f"Successfully deleted ECI instance {container_group_id}.")
        except Exception as error:
            # If the instance is already gone, that's okay.
            if "not exist" in str(error):
                print(f"ECI instance {container_group_id} was already deleted.")
                return
            print(f"FAILED to delete ECI instance {container_group_id}. Error: {error}")
            if hasattr(error, 'data') and error.data.get("Recommend"):
                print(f"Aliyun Recommend: {error.data.get('Recommend')}")
            raise error

    async def execute_command(
        self, 
        region_id: str,
        container_group_id: str,
        container_name: str, # 我们需要知道在哪个容器里执行
        command: str,
        timeout_seconds: int = 20
    ) -> Tuple[bool, str]:
        """
        Executes a command in a specified container of an ECI instance.

        Returns:
            A tuple of (success, output_string).
        """
        client = self._create_client(region_id)
        exec_request = eci_models.ExecContainerCommandRequest(
            region_id=region_id,
            container_group_id=container_group_id,
            container_name=container_name,
            command=["/bin/sh", "-c", command] # 使用 sh -c 来执行复杂命令
        )

        try:
            print(f"[{container_group_id}] Requesting exec WebSocket URL for command: {command[:50]}...")
            exec_response = await client.exec_container_command_with_options_async(exec_request, util_models.RuntimeOptions())
            
            websocket_uri = exec_response.body.web_socket_uri
            if not websocket_uri:
                raise Exception("Failed to get a WebSocket URI for exec.")

            print(f"[{container_group_id}] Got WebSocket URI, connecting...")
            
            output_buffer = []

            # 使用 aiohttp 连接到阿里云返回的 WebSocket URI
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(websocket_uri, timeout=timeout_seconds) as ws:
                    # 连接后，阿里云的 exec stream 是双向的
                    # 我们不需要发送任何 stdin，只需要接收 stdout/stderr
                    # 阿里云的流协议会在每条消息前加一个字节表示流类型 (0x01 for stdout, 0x02 for stderr)
                    
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            # 忽略第一个字节（流类型指示符）
                            data = msg.data[1:]
                            output_buffer.append(data.decode('utf-8', errors='ignore'))
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise Exception(f"Exec WebSocket connection error: {ws.exception()}")

            full_output = "".join(output_buffer)
            print(f"[{container_group_id}] Command executed. Output: {full_output[:100]}...")
            # 简单的成功判断：如果输出了 "error", "failed", "not found" 等词，则认为失败
            # 更可靠的方式是让命令自己输出成功/失败标记，例如 `... && echo "SUCCESS"`
            if any(err in full_output.lower() for err in ["error", "failed", "not found", "no such file"]):
                return False, f"Command execution likely failed. Output:\n{full_output}"
            else:
                return True, full_output

        except Exception as e:
            print(f"[{container_group_id}] FAILED to execute command. Error: {e}")
            return False, str(e)

# Create a single instance of the service to be used throughout the application
aliyun_service = AliyunECIService()