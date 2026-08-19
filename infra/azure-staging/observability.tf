resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.base_name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = var.log_retention_days

  # A daily cap is what keeps an unexpected log volume from turning a $21.80/month
  # estimate into a surprise. Ingestion stops for the day rather than billing on.
  daily_quota_gb = 1

  tags = local.common_tags
}

resource "azurerm_application_insights" "main" {
  name                = "appi-${local.base_name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  sampling_percentage = 100
  tags                = local.common_tags
}

resource "azurerm_monitor_action_group" "cost" {
  count               = length(var.budget_alert_emails) == 0 ? 0 : 1
  name                = "ag-${local.base_name}-cost"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "cost"

  dynamic "email_receiver" {
    for_each = var.budget_alert_emails
    content {
      name                    = "recipient-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

# Spending is gated by approval, so the budget is a hard requirement rather than a
# nicety: apply fails if nobody is listed to receive the alerts.
resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-${local.base_name}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.monthly_budget_usd
  time_grain        = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  dynamic "notification" {
    for_each = { forecast = "Forecasted", actual_80 = "Actual", actual_100 = "Actual" }
    content {
      enabled        = true
      threshold      = notification.key == "actual_100" ? 100 : 80
      operator       = "GreaterThanOrEqualTo"
      threshold_type = notification.value
      contact_emails = var.budget_alert_emails
      contact_groups = length(var.budget_alert_emails) == 0 ? [] : [azurerm_monitor_action_group.cost[0].id]
    }
  }

  lifecycle {
    # timestamp() changes on every plan; the start date is only meaningful at create.
    ignore_changes = [time_period]

    precondition {
      condition     = length(var.budget_alert_emails) > 0
      error_message = "budget_alert_emails must contain at least one address: paid capacity is not provisioned without a cost alert recipient."
    }
  }
}
