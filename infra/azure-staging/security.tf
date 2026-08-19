resource "azurerm_key_vault" "main" {
  name                       = "kv-${local.base_name}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 7

  # RBAC rather than access policies, so secret access is auditable through the
  # same role assignments as everything else.
  rbac_authorization_enabled = true
  tags                       = local.common_tags
}

resource "azurerm_role_assignment" "vault_admin" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "vault_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.workload.principal_id
}

# The generated database password never appears in a variable file, in an
# environment variable, or in the container definition. The workload reads it from
# the vault through its managed identity.
resource "azurerm_key_vault_secret" "postgres_password" {
  name         = "postgres-administrator-password"
  value        = random_password.postgres.result
  key_vault_id = azurerm_key_vault.main.id
  content_type = "password"

  depends_on = [azurerm_role_assignment.vault_admin]
}

resource "azurerm_key_vault_secret" "database_url" {
  name = "fraud-database-url"
  value = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    var.postgres_administrator_login,
    urlencode(random_password.postgres.result),
    azurerm_postgresql_flexible_server.main.fqdn,
    azurerm_postgresql_flexible_server_database.main.name,
  )
  key_vault_id = azurerm_key_vault.main.id
  content_type = "connection-string"

  depends_on = [azurerm_role_assignment.vault_admin]
}

resource "random_password" "link_hmac_key" {
  length  = 48
  special = false
}

resource "azurerm_key_vault_secret" "link_hmac_key" {
  name         = "fraud-link-hmac-key"
  value        = random_password.link_hmac_key.result
  key_vault_id = azurerm_key_vault.main.id
  content_type = "hmac-key"

  depends_on = [azurerm_role_assignment.vault_admin]
}
