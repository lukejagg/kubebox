import json
import logging
import asyncio
import time  # Ensure this import is at the top of the file
from typing import Tuple  # Added logging package
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KubeboxPodExistsError(Exception):
    """Exception raised when a pod already exists."""


class KubeboxPod:
    def __init__(self, name: str, namespace: str, kubebox: "Kubebox" = None):
        self.name = name
        self.namespace = namespace
        self._kubebox = kubebox

    async def wait_until_ready(self, poll_interval: float = 0.1):
        start_time = asyncio.get_event_loop().time()
        while True:
            try:
                pod = await asyncio.to_thread(
                    self._kubebox._core_v1.read_namespaced_pod,
                    name=self.name,
                    namespace=self.namespace,
                )
                status = pod.status
                if status.phase == "Running":
                    # Check if containers are ready
                    all_ready = all([c.ready for c in status.container_statuses])
                    if all_ready:
                        elapsed = asyncio.get_event_loop().time() - start_time
                        logging.info(
                            f"Pod '{self.name}' is ready. Time taken: {elapsed:.2f} seconds."
                        )
                        return elapsed
            except ApiException as e:
                logging.error(f"Exception when reading pod status: {e}")
                break
            await asyncio.sleep(poll_interval)


class KubeboxService:
    def __init__(self, name: str, namespace: str, kubebox: "Kubebox" = None):
        self.name = name
        self.namespace = namespace
        self._kubebox = kubebox

    async def get_external_ip(self, timeout: float = 5, poll_interval: float = 0.1):
        """
        Asynchronously waits for the external IP of the service to become available.

        :param timeout: Maximum time to wait for the external IP in seconds.
        :param poll_interval: Time to wait between polls in seconds.
        :return: The external IP or hostname of the service.
        :raises TimeoutError: If the external IP is not available within the timeout period.
        """
        logging.info(f"Waiting for external IP of service '{self.name}'...")
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                # Use asyncio.to_thread to run the blocking I/O operation in a separate thread
                service = await asyncio.to_thread(
                    self._kubebox._core_v1.read_namespaced_service,
                    name=self.name,
                    namespace=self.namespace
                )
                ingress = service.status.load_balancer.ingress
                if ingress:
                    ip = ingress[0].ip or ingress[0].hostname
                    if ip:
                        logging.info(f"Service '{self.name}' is available at {ip}.")
                        return ip
            except ApiException as e:
                logging.error(f"Exception when reading service status: {e}")
                # Consider whether to break or continue based on the type of exception

            await asyncio.sleep(poll_interval)

        raise TimeoutError(f"Timed out waiting for external IP of service '{self.name}'.")


class Kubebox:
    def __init__(self, terraform_path: str):
        self.terraform_path = terraform_path
        self._load_kube_config_from_terraform(terraform_path)

        self._client = client.ApiClient()
        self._core_v1 = client.CoreV1Api()

    def create_pod(
        self,
        pod_name: str,
        namespace: str = "default",
        image: str = "lukejagg/sandbox:latest",
        username: str = None,
    ):
        logging.info(
            f"Creating pod: {pod_name} in namespace: {namespace} with image: {image}"
        )

        labels = {"app": pod_name}
        if username:
            labels["username"] = username

        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": pod_name, "namespace": namespace, "labels": labels},
            "spec": {
                "containers": [
                    {
                        "name": pod_name,
                        "image": image,
                    }
                ]
            },
        }

        try:
            api_response = self._core_v1.create_namespaced_pod(
                namespace=namespace, body=pod_manifest
            )
            logging.info(f"Pod {pod_name} created successfully")
            return KubeboxPod(pod_name, namespace, kubebox=self)
        except ApiException as e:
            if e.status == 409:
                logging.info(f"Pod {pod_name} already exists in namespace {namespace}")
                # try:
                #     api_response = self._core_v1.replace_namespaced_pod(
                #         name=name, namespace=namespace, body=pod_manifest
                #     )
                #     logging.info(f"Pod {name} updated successfully")
                #     return KubeboxPod(name, namespace, kubebox=self)
                # except ApiException as update_e:
                #     logging.error(f"Error updating pod {name}: {update_e}")
                #     raise update_e
                return KubeboxPod(pod_name, namespace, kubebox=self)
            else:
                logging.error(f"Error creating pod {pod_name}: {e}")
                raise e

    def create_service(
        self,
        pod_name: str,
        namespace: str = "default",
        username: str = None,
        ports: list[int] = [],
    ):
        logging.info(f"Creating service: {pod_name}-service in namespace: {namespace}")

        labels = {"app": pod_name}
        if username:
            labels["username"] = username

        service_name = f"{pod_name}-service"
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": service_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "selector": {"app": pod_name},
                "ports": [
                    {"name": "api", "protocol": "TCP", "port": 80, "targetPort": 80},
                    *[
                        {
                            "name": f"dev-{port}",
                            "protocol": "TCP",
                            "port": port,
                            "targetPort": port,
                        }
                        for port in ports
                    ],
                ],
                "type": "LoadBalancer",
                "externalTrafficPolicy": "Local",
            },
        }

        try:
            api_response = self._core_v1.create_namespaced_service(
                namespace=namespace, body=service_manifest
            )
            logging.info(f"Service {service_name} created successfully")
            return KubeboxService(service_name, namespace, kubebox=self)
        except ApiException as e:
            if e.status == 409:
                logging.info(
                    f"Service {service_name} already exists in namespace {namespace}"
                )
                try:
                    api_response = self._core_v1.replace_namespaced_service(
                        name=service_name, namespace=namespace, body=service_manifest
                    )
                    logging.info(f"Service {service_name} updated successfully")
                    return KubeboxService(service_name, namespace, kubebox=self)
                except ApiException as update_e:
                    logging.error(f"Error updating service {service_name}: {update_e}")
                    raise update_e
            else:
                logging.error(f"Error creating service {service_name}: {e}")
                raise e

    def _load_kube_config_from_terraform(self, tfstate_file):
        with open(tfstate_file, "r") as f:
            tfstate = json.load(f)  # Use json.load instead of hcl2.load

        # Navigate the state file to find the kubeconfig data
        resources = tfstate.get("resources", [])
        kube_config = None

        for resource in resources:
            if resource.get("type") == "azurerm_kubernetes_cluster":
                for instance in resource.get("instances", []):
                    attributes = instance.get("attributes", {})
                    # Check for 'kube_config_raw' or 'kube_admin_config_raw'
                    kube_config_raw = attributes.get(
                        "kube_config_raw"
                    ) or attributes.get("kube_admin_config_raw")
                    if kube_config_raw:
                        # Decode the base64-encoded kubeconfig
                        # kube_config = base64.b64decode(kube_config_raw).decode('utf-8')
                        kube_config = kube_config_raw
                        break
                if kube_config:
                    break

        if not kube_config:
            raise Exception("Failed to find kube_config in terraform state file.")

        # Write the kubeconfig to a temporary file
        kubeconfig_path = "/tmp/kubeconfig"
        with open(kubeconfig_path, "w") as f:
            f.write(kube_config)

        # Load the kubeconfig
        config.load_kube_config(config_file=kubeconfig_path)


if __name__ == "__main__":

    def setup_logging():
        RESET = "\033[0m"
        COLORS = {
            "DEBUG": "\033[34m",  # Blue
            "INFO": "\033[32m",  # Green
            "WARNING": "\033[33m",  # Yellow
            "ERROR": "\033[31m",  # Red
            "CRITICAL": "\033[41m",  # Red background
        }

        class CustomFormatter(logging.Formatter):
            def format(self, record):
                log_fmt = f"{COLORS.get(record.levelname, RESET)}%(asctime)s - %(levelname)s - %(message)s{RESET}"
                formatter = logging.Formatter(log_fmt, datefmt="%Y-%m-%d %H:%M:%S")
                return formatter.format(record)

        # Set up the root logger
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger()

        # Remove default handlers and add the custom handler
        if logger.hasHandlers():
            logger.handlers.clear()

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(CustomFormatter())
        logger.addHandler(console_handler)

    async def main():
        kubebox = Kubebox("./apps/sandbox/terraform.tfstate")

        pod = kubebox.create_pod("test", username="test")
        service = kubebox.create_service("test", username="test")

        await pod.wait_until_ready()
        ip = await service.get_external_ip()
        print(f"http://{ip}")

    setup_logging()
    asyncio.run(main())
