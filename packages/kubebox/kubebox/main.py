import os
import time
import base64
import json  # Use json instead of hcl2
import requests
import yaml
from kubernetes import client, config
from kubernetes.client.rest import ApiException

# Path to your terraform state file
TERRAFORM_STATE_FILE = "../../apps/sandbox/terraform.tfstate"

# User for whom we're creating the pod
USER_NAME = "luke3"

# Docker image to use (replace with your actual image)
DOCKER_IMAGE = "lukejagg/sandbox:latest"


def get_public_ip():
    # Get the public IP address using an external service
    response = requests.get("https://api.ipify.org?format=json")
    return response.json()["ip"]


def load_kube_config_from_terraform(tfstate_file):
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
                kube_config_raw = attributes.get("kube_config_raw") or attributes.get(
                    "kube_admin_config_raw"
                )
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


def create_pod_and_service(api_instance, core_v1, user_name, image):
    # Define pod metadata and spec
    pod_name = f"{user_name}-pod"
    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": pod_name, "labels": {"app": user_name}},
        "spec": {
            "containers": [
                {
                    "name": f"{user_name}-container",
                    "image": image,
                    "ports": [{"containerPort": 80}],
                }
            ]
        },
    }

    # Create the pod
    try:
        api_response = core_v1.create_namespaced_pod(
            namespace="default", body=pod_manifest
        )
        print(f"Pod '{pod_name}' created.")
    except ApiException as e:
        if e.status == 409:
            print(f"Pod '{pod_name}' already exists.")
        else:
            print("Exception when creating pod: %s\n" % e)
            return None, None

    # Define service to expose the pod
    service_name = f"{user_name}-service"
    service_manifest = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": service_name},
        "spec": {
            "selector": {"app": user_name},
            "ports": [{"protocol": "TCP", "port": 80, "targetPort": 80}],
            "type": "LoadBalancer",
            "externalTrafficPolicy": "Local",
        },
    }

    # Create or update the service
    try:
        api_response = core_v1.create_namespaced_service(
            namespace="default", body=service_manifest
        )
        print(f"Service '{service_name}' created.")
    except ApiException as e:
        if e.status == 409:
            # Service already exists, update it
            try:
                api_response = core_v1.replace_namespaced_service(
                    name=service_name, namespace="default", body=service_manifest
                )
                print(f"Service '{service_name}' updated.")
            except ApiException as update_e:
                print("Exception when updating service: %s\n" % update_e)
                return None, None
        else:
            print("Exception when creating service: %s\n" % e)
            return None, None

    return pod_name, service_name


def wait_for_pod_ready(core_v1, pod_name):
    start_time = time.time()
    while True:
        try:
            pod = core_v1.read_namespaced_pod(name=pod_name, namespace="default")
            status = pod.status
            if status.phase == "Running":
                # Check if containers are ready
                all_ready = all([c.ready for c in status.container_statuses])
                if all_ready:
                    elapsed = time.time() - start_time
                    print(
                        f"Pod '{pod_name}' is ready. Time taken: {elapsed:.2f} seconds."
                    )
                    return elapsed
        except ApiException as e:
            print("Exception when reading pod status: %s\n" % e)
            break
        time.sleep(2)


def get_service_external_ip(core_v1, service_name):
    print("Waiting for service external IP...")
    while True:
        try:
            service = core_v1.read_namespaced_service(
                name=service_name, namespace="default"
            )
            ingress = service.status.load_balancer.ingress
            if ingress:
                ip = ingress[0].ip or ingress[0].hostname
                if ip:
                    print(f"Service '{service_name}' is available at {ip}.")
                    return ip
        except ApiException as e:
            print("Exception when reading service status: %s\n" % e)
            break
        time.sleep(2)


def create_or_update_network_policy(api_instance, user_name, allowed_ip):
    policy_name = f"{user_name}-network-policy"
    network_policy_manifest = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": policy_name},
        "spec": {
            "podSelector": {"matchLabels": {"app": user_name}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {
                            "ipBlock": {"cidr": f"{allowed_ip}/32"}
                        }
                    ]
                }
            ],
            "egress": [
                {
                    "to": [
                        {
                            "ipBlock": {"cidr": f"{allowed_ip}/32"}
                        }
                    ]
                }
            ],
            # "ingress": [],  # No ingress rules, block all incoming traffic
            # "egress": [],   # No egress rules, block all outgoing traffic
        },
    }

    try:
        api_response = api_instance.replace_namespaced_network_policy(
            name=policy_name, namespace="default", body=network_policy_manifest
        )
        print(f"Network Policy '{policy_name}' updated.")
    except ApiException as e:
        if e.status == 404:
            # If the policy does not exist, create it
            try:
                api_response = api_instance.create_namespaced_network_policy(
                    namespace="default", body=network_policy_manifest
                )
                print(f"Network Policy '{policy_name}' created.")
            except ApiException as create_e:
                print("Exception when creating network policy: %s\n" % create_e)
        else:
            print("Exception when updating network policy: %s\n" % e)


def main():
    print("Starting Kubernetes deployment process...")

    public_ip = get_public_ip()
    # print(f"Public IP: {public_ip}")    

    # Load Kubernetes configuration
    print("Loading Kubernetes configuration from Terraform state file...")
    load_kube_config_from_terraform(TERRAFORM_STATE_FILE)
    print("Kubernetes configuration loaded successfully.")

    # Create API clients
    print("Creating Kubernetes API clients...")
    core_v1 = client.CoreV1Api()
    print("Kubernetes API clients created.")

    # Create pod and service
    print("Creating pod and service...")
    pod_name, service_name = create_pod_and_service(
        client.ApiClient(), core_v1, USER_NAME, DOCKER_IMAGE
    )
    if not pod_name or not service_name:
        print("Failed to create pod or service.")
        return
    print(f"Pod '{pod_name}' and service '{service_name}' created successfully.")

    # Create network policy to restrict access
    print("Creating network policy to restrict access...")
    create_or_update_network_policy(client.NetworkingV1Api(), USER_NAME, public_ip)
    print("Network policy created successfully.")

    # Wait for pod to be ready and measure time
    print(f"Waiting for pod '{pod_name}' to be ready...")
    pod_startup_time = wait_for_pod_ready(core_v1, pod_name)
    print(f"Pod '{pod_name}' is ready. Startup time: {pod_startup_time:.2f} seconds.")

    # Get the external IP of the service
    print(f"Retrieving external IP for service '{service_name}'...")
    external_ip = get_service_external_ip(core_v1, service_name)
    if not external_ip:
        print("Failed to retrieve the external IP of the service.")
        return
    print(f"Service '{service_name}' is available at external IP: {external_ip}")

    # Output the results
    print("\n--- Deployment Summary ---")
    print(f"User: {USER_NAME}")
    print(f"Pod Name: {pod_name}")
    print(f"Service Name: {service_name}")
    print(f"Pod Startup Time: {pod_startup_time:.2f} seconds")
    print(f"Service External IP: {external_ip}")
    print(f"Access the application at: http://{external_ip}/")


if __name__ == "__main__":
    main()
