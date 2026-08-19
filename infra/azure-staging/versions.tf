# Azure staging infrastructure for the application fraud strategy platform.
#
# AUTHORED ONLY. This configuration has never been applied and no Azure resource
# exists. Applying it spends money and requires both `deployment` and
# `paid-capacity` approval in the private delivery record, neither of which has been
# requested. See README.md in this directory before running anything.

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.20"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State must not live on a workstation for a shared environment. The backend is
  # left unconfigured on purpose: choosing a storage account is part of the
  # deployment decision, not of authoring, and hard-coding one here would imply a
  # resource that does not exist.
  #
  # backend "azurerm" {
  #   resource_group_name  = "<state resource group>"
  #   storage_account_name = "<state storage account>"
  #   container_name       = "tfstate"
  #   key                  = "fraud-strategy/staging.tfstate"
  # }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy    = false
      recover_soft_deleted_key_vaults = true
    }
    resource_group {
      # Refuse to delete a resource group that still contains resources, so a
      # teardown that misses something fails loudly instead of silently.
      prevent_deletion_if_contains_resources = true
    }
  }
}

provider "random" {}
