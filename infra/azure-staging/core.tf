locals {
  # Several Azure resource types reject hyphens or cap length, so names are built
  # from the alphanumeric project slug rather than from a display name.
  suffix    = "${var.project}${var.environment}"
  base_name = "${var.project}-${var.environment}"

  common_tags = merge(var.tags, {
    environment = var.environment
  })
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = "rg-${local.base_name}"
  location = var.location
  tags     = local.common_tags
}

# One user-assigned identity for the web app and the job. Both reach the registry,
# Key Vault, and storage through it, so no connection secret is ever placed in an
# environment variable.
resource "azurerm_user_assigned_identity" "workload" {
  name                = "id-${local.base_name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_container_registry" "main" {
  name                = "cr${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # Pull with the managed identity, never with an admin password.
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}
