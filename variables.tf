# variables.tf

variable "docker_username" {
  description = "Your Docker registry username"
}

variable "docker_password" {
  description = "Your Docker registry password"
  sensitive   = true
}

variable "docker_email" {
  description = "Your Docker registry email"
}
