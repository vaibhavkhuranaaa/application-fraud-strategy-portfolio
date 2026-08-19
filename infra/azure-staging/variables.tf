variable "project" {
  description = "Short project slug used to name resources."
  type        = string
  default     = "fraudstrategy"

  validation {
    condition     = can(regex("^[a-z0-9]{3,16}$", var.project))
    error_message = "project must be 3-16 lowercase alphanumeric characters; several Azure resource names disallow hyphens."
  }
}

variable "environment" {
  description = "Environment name. Only staging is costed and approved as a design."
  type        = string
  default     = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "location" {
  description = "Azure region. The recorded price evidence was collected for East US 2."
  type        = string
  default     = "eastus2"
}

variable "postgres_sku_name" {
  description = "PostgreSQL Flexible Server SKU. B_Standard_B1ms is the costed staging choice."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "PostgreSQL storage in MB. 32 GB is the costed staging choice."
  type        = number
  default     = 32768
}

variable "postgres_backup_retention_days" {
  description = "Point-in-time restore window. The recovery contract requires seven days in staging."
  type        = number
  default     = 7

  validation {
    condition     = var.postgres_backup_retention_days >= 7
    error_message = "The recovery contract requires at least seven days of PITR."
  }
}

variable "postgres_administrator_login" {
  description = "PostgreSQL administrator login. The password is generated and stored in Key Vault; it is never set here."
  type        = string
  default     = "fraud_admin"
}

variable "container_image" {
  description = "Fully qualified image reference for the web app and job. Must be pushed to the registry before apply."
  type        = string
  default     = ""
}

variable "web_min_replicas" {
  description = "Minimum web replicas. Zero enables scale-to-zero, which is what keeps staging inside the documented cost floor."
  type        = number
  default     = 0
}

variable "web_max_replicas" {
  description = "Maximum web replicas."
  type        = number
  default     = 2
}

variable "batch_schedule_cron" {
  description = "Cron expression for the scheduled scoring job, in UTC."
  type        = string
  default     = "0 3 * * *"
}

variable "log_retention_days" {
  description = "Log Analytics retention. Thirty days is the minimum the workspace accepts."
  type        = number
  default     = 30
}

variable "monthly_budget_usd" {
  description = "Consumption budget in USD. The recorded staging estimate is about $21.80/month fixed before requests, egress, and tax."
  type        = number
  default     = 40
}

variable "budget_alert_emails" {
  description = "Addresses that receive cost alerts. Apply fails without at least one, so no budget is created that nobody watches."
  type        = list(string)
  default     = []
}

variable "allowed_client_ip" {
  description = "Single client address allowed to reach PostgreSQL directly, in CIDR-free form. Empty means no public client rule is created."
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    project    = "application-fraud-strategy-portfolio"
    managed_by = "terraform"
    data_class = "synthetic-licensed"
  }
}
