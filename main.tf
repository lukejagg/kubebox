# main.tf

# Step 1: Define the Azure provider
provider "azurerm" {
  features {}
}

# Step 2: Create a Resource Group
resource "azurerm_resource_group" "aks_rg" {
  name     = "myResourceGroup"
  location = "East US"
}

# Step 3: Create the AKS Cluster
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
}

# Step 4: Configure the Kubernetes Provider
provider "kubernetes" {
  host                   = azurerm_kubernetes_cluster.aks.kube_config.0.host
  client_certificate     = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.client_certificate)
  client_key             = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.client_key)
  cluster_ca_certificate = base64decode(azurerm_kubernetes_cluster.aks.kube_config.0.cluster_ca_certificate)
}

# Step 5: Create a Kubernetes Namespace
resource "kubernetes_namespace" "example" {
  metadata {
    name = "myapp"
  }
}

# Step 6: (Optional) Create Kubernetes Secret for Private Docker Registry
# Use variables for sensitive data
resource "kubernetes_secret" "docker_secret" {
  metadata {
    name      = "regcred"
    namespace = kubernetes_namespace.example.metadata[0].name
  }

  data = {
    ".dockerconfigjson" = base64encode(jsonencode({
      auths = {
        "https://index.docker.io/v1/" = {
          username = var.docker_username
          password = var.docker_password
          email    = var.docker_email
          auth     = base64encode("${var.docker_username}:${var.docker_password}")
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
        # Correct placement of image_pull_secrets
        image_pull_secrets {
          name = kubernetes_secret.docker_secret.metadata[0].name
        }

        container {
          name  = "myapp-container"
          image = "lukejagg/sandbox:latest" # Replace with your Docker image

          port {
            container_port = 80
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
