# main.tf

# Step 1: Define the Azure provider
provider "azurerm" {
  features {}

  subscription_id = var.subscription_id
  client_id       = var.client_id
  client_secret   = var.client_secret
  tenant_id       = var.tenant_id
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
    vm_size    = "Standard_DS3_v2"
    temporary_name_for_rotation = "defaulttemp"
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
    ".dockerconfigjson" = jsonencode({
      auths = {
        "https://index.docker.io/v1/" = {
          auth     = base64encode("${var.docker_username}:${var.docker_password}")
        }
      }
    })
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
        image_pull_secrets {
          name = kubernetes_secret.docker_secret.metadata[0].name
        }

        container {
          name  = "myapp-container"
          image = "lukejagg/sandbox:latest" # Replace with your Docker image

          port {
            container_port = 80
          }

          resources {
            requests = {
              cpu    = "1000m"
              memory = "1024Mi"
            }
            limits = {
              cpu    = "4000m"
              memory = "4096Mi"
            }
          }
        }
      }
    }
  }
}

// # For AKS, you can enable autoscaling via Terraform
// resource "azurerm_kubernetes_cluster_node_pool" "default" {
//   name                = "default"
//   kubernetes_cluster_id = azurerm_kubernetes_cluster.aks.id
//   vm_size             = "Standard_DS2_v2"
//   node_count          = 2
//   min_count           = 2
//   max_count           = 5
//   enable_auto_scaling = true
// }

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
