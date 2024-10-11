# variables.tf

variable "docker_username" {
  description = "Your Docker registry username"
}

variable "docker_password" {
  description = "Your Docker registry password"
  sensitive   = true
}

variable "subscription_id" {
  description = "Your Azure subscription ID"
}

variable "client_id" {
  description = "Your Azure client ID"
}

variable "client_secret" {
  description = "Your Azure client secret"
  sensitive   = true
}

variable "tenant_id" {
  description = "Your Azure tenant ID"
}
