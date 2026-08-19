output "resource_group_name" {
  description = "Resource group holding every staging resource. Teardown deletes this group."
  value       = azurerm_resource_group.main.name
}

output "container_registry_login_server" {
  description = "Registry to push the worker image to before the first apply that sets container_image."
  value       = azurerm_container_registry.main.login_server
}

output "web_url" {
  description = "Public HTTPS endpoint for the workbench."
  value       = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "postgres_fqdn" {
  description = "PostgreSQL host name. Credentials live in Key Vault, never in state output."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "key_vault_name" {
  description = "Vault holding the database URL and the linking HMAC key."
  value       = azurerm_key_vault.main.name
}

output "artifact_storage_account" {
  description = "ADLS Gen2 account for curated Parquet and model artifacts."
  value       = azurerm_storage_account.artifacts.name
}

output "workload_identity_client_id" {
  description = "Client ID the application uses for managed-identity access."
  value       = azurerm_user_assigned_identity.workload.client_id
}

output "monthly_budget_usd" {
  description = "Configured consumption budget. The recorded fixed staging estimate is about $21.80/month."
  value       = azurerm_consumption_budget_resource_group.main.amount
}
