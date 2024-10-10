# main.tf

# Step 1: Define the provider
provider "azurerm" {
  features {}
}

provider "kubernetes" {
  host                   = azurerm_kubernetes_cluster.aks.kube_config.0.host
  client_certificate      = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.client_certificate)
  client_key              = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.client_key)
  cluster_ca_certificate  = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.cluster_ca_certificate)
}

# Step 2: Create a Resource Group
resource "azurerm_resource_group" "aks_rg" {
  name     = "myResourceGroup"
  location = "East US"
}

# Step 3: Create an Azure Container Registry (optional, skip if using Docker Hub)
resource "azurerm_container_registry" "acr" {
  name                = "myacrregistry"
  resource_group_name = azurerm_resource_group.aks_rg.name
  location            = azurerm_resource_group.aks_rg.location
  sku                 = "Basic"
  admin_enabled       = true
}

# Step 4: Create the AKS cluster
resource "azurerm_kubernetes_cluster" "aks" {
  name                = "myAKSCluster"
  location            = azurerm_resource_group.aks_rg.location
  resource_group_name = azurerm_resource_group.aks_rg.name
  dns_prefix          = "myakscluster"

  default_node_pool {
    name       = "default"
    node_count = 2
    vm_size    = "Standard_DS2_v2"
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin = "azure"
  }
}

# Step 5: Create a Kubernetes Namespace
resource "kubernetes_namespace" "example" {
  metadata {
    name = "myapp"
  }
}

# Step 6: (Optional) Create Kubernetes Secret for Private Docker Registry
# This is needed if the image is private (replace the Docker Hub example with Azure Container Registry if needed).
resource "kubernetes_secret" "docker_secret" {
  metadata {
    name      = "regcred"
    namespace = kubernetes_namespace.example.metadata[0].name
  }

  data = {
    ".dockerconfigjson" = base64encode(jsonencode({
      auths = {
        "https://index.docker.io/v1/" = {
          username = "myusername"
          password = "mypassword"
          email    = "myemail@example.com"
          auth     = base64encode("myusername:mypassword")
        }
      }
    }))
  }

  type = "kubernetes.io/dockerconfigjson"
}

# Step 7: Create a Kubernetes Deployment
resource "kubernetes_deployment" "myapp_deployment" {
  metadata {
    name      = "myapp-deployment"
    namespace = kubernetes_namespace.example.metadata[0].name
  }

  spec {
    replicas = 2

    selector {
      match_labels = {
        app = "myapp"
      }
    }

    template {
      metadata {
        labels = {
          app = "myapp"
        }
      }

      spec {
        container {
          name  = "myapp-container"
          image = "myusername/myapp:latest" # Change this to your Docker image

          port {
            container_port = 80
          }

          # Use the secret for pulling images from private registry
          image_pull_secrets {
            name = kubernetes_secret.docker_secret.metadata[0].name
          }
        }
      }
    }
  }
}

# Step 8: Expose the Deployment via a Kubernetes Service
resource "kubernetes_service" "myapp_service" {
  metadata {
    name      = "myapp-service"
    namespace = kubernetes_namespace.example.metadata[0].name
  }

  spec {
    selector = {
      app = "myapp"
    }

    port {
      port        = 80
      target_port = 80
    }

    type = "LoadBalancer"
  }
}