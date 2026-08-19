# ADLS Gen2 for model artifacts and curated Parquet. Raw BAF files and the linking
# fixture's entity/ring truth are never uploaded: the dataset licence and the
# evaluation contract both keep them local.
resource "azurerm_storage_account" "artifacts" {
  name                            = "st${local.suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS" # Staging only; the production profile uses ZRS.
  account_kind                    = "StorageV2"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false # Force identity-based access.
  public_network_access_enabled   = true
  tags                            = local.common_tags

  blob_properties {
    versioning_enabled = true # Artifact rollback depends on versioned object paths.

    delete_retention_policy {
      days = 14
    }
  }
}

resource "azurerm_storage_container" "artifacts" {
  name                  = "artifacts"
  storage_account_id    = azurerm_storage_account.artifacts.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "curated" {
  name                  = "curated"
  storage_account_id    = azurerm_storage_account.artifacts.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "storage_contributor" {
  scope                = azurerm_storage_account.artifacts.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

resource "random_password" "postgres" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${local.base_name}"
  resource_group_name           = azurerm_resource_group.main.name
  location                      = azurerm_resource_group.main.location
  version                       = "17"
  sku_name                      = var.postgres_sku_name
  storage_mb                    = var.postgres_storage_mb
  backup_retention_days         = var.postgres_backup_retention_days
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = true
  zone                          = "1"
  tags                          = local.common_tags

  administrator_login    = var.postgres_administrator_login
  administrator_password = random_password.postgres.result

  authentication {
    password_auth_enabled         = true
    active_directory_auth_enabled = true
    tenant_id                     = data.azurerm_client_config.current.tenant_id
  }

  lifecycle {
    # Storage cannot be reduced in place, and an accidental shrink would destroy the
    # server rather than fail.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "fraud_strategy"
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "utf8"

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_postgresql_flexible_server_configuration" "require_ssl" {
  name      = "require_secure_transport"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "ON"
}

# Container Apps egress addresses are not static on the Consumption profile, so
# staging allows Azure services and, optionally, one named client address. This is
# the weakest part of the staging design and is called out in the README.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "client" {
  count            = var.allowed_client_ip == "" ? 0 : 1
  name             = "allow-named-client"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = var.allowed_client_ip
  end_ip_address   = var.allowed_client_ip
}
