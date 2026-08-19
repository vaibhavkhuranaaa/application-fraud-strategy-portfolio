resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.base_name}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.common_tags
}

# Scale-to-zero web app. min_replicas = 0 is what keeps an idle staging environment
# inside the documented monthly free grant for Container Apps.
resource "azurerm_container_app" "web" {
  name                         = "ca-${local.base_name}-web"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.workload.id
  }

  secret {
    name                = "fraud-database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.id
    identity            = azurerm_user_assigned_identity.workload.id
  }

  ingress {
    external_enabled = true
    target_port      = 8050
    transport        = "auto"

    # HTTPS only. Plain HTTP is redirected rather than served.
    allow_insecure_connections = false

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.web_min_replicas
    max_replicas = var.web_max_replicas

    container {
      name   = "workbench"
      image  = var.container_image
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "FRAUD_DATABASE_URL"
        secret_name = "fraud-database-url"
      }

      env {
        name  = "FRAUD_ARTIFACT_ROOT"
        value = "https://${azurerm_storage_account.artifacts.name}.blob.core.windows.net/artifacts"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.workload.client_id
      }

      env {
        name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        value = azurerm_application_insights.main.connection_string
      }

      liveness_probe {
        transport = "HTTP"
        port      = 8050
        path      = "/"
      }

      readiness_probe {
        transport = "HTTP"
        port      = 8050
        path      = "/"
      }
    }
  }

  lifecycle {
    precondition {
      condition     = var.container_image != ""
      error_message = "container_image must be set to an image already pushed to the registry."
    }
  }
}

# Scheduled batch scoring. Separate from the web app so a long batch cannot consume
# the request path's replicas, and so it can be run on demand for a retry.
resource "azurerm_container_app_job" "batch" {
  name                         = "caj-${local.base_name}-batch"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = azurerm_container_app_environment.main.id
  replica_timeout_in_seconds   = 3600
  replica_retry_limit          = 1
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.workload.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.workload.id
  }

  secret {
    name                = "fraud-database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.id
    identity            = azurerm_user_assigned_identity.workload.id
  }

  schedule_trigger_config {
    cron_expression          = var.batch_schedule_cron
    parallelism              = 1
    replica_completion_count = 1
  }

  template {
    container {
      name    = "worker"
      image   = var.container_image
      cpu     = 1.0
      memory  = "2Gi"
      command = ["python", "-m", "fraud_strategy.cli"]
      args    = ["migrate", "--load-data"]

      env {
        name        = "FRAUD_DATABASE_URL"
        secret_name = "fraud-database-url"
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.workload.client_id
      }
    }
  }
}
