# FILE: services/aliyun_eci.py

import asyncio
import time
from typing import Tuple

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

# Create a single instance of the service to be used throughout the application
aliyun_service = AliyunECIService()