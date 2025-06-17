terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "6.39.0"
    }
  }
}

provider "google" {
  project = "mtg-commander-picker"
  region  = "us-central1"
}

# 1. Service Account for Sheets API
resource "google_service_account" "sheets_sa" {
  account_id   = "mtg-commander-picker-sheets"
  display_name = "MTG Commander Picker Sheets Service Account"
}

# 2. Key for that Service Account
resource "google_service_account_key" "sheets_key" {
  service_account_id = google_service_account.sheets_sa.name
}

# 3. Define the Secret in Secret Manager
resource "google_secret_manager_secret" "sheets_creds" {
  secret_id = "mtg-commander-picker-sheets-creds"

  replication {
    auto {}
  }

  # Optional labels are fine, but no `description` field here
  labels = {
    app = "mtg-commander-picker"
    env = "prod"
  }
}

# 4. Push the key material into a new version (write‑only)
resource "google_secret_manager_secret_version" "sheets_creds_version" {
  secret         = google_secret_manager_secret.sheets_creds.id
  secret_data_wo = base64encode(google_service_account_key.sheets_key.private_key)
}

resource "google_project_service" "sheets_api" {
  project = "mtg-commander-picker"
  service = "sheets.googleapis.com"
}

resource "google_project_service" "drive_api" {
  project = "mtg-commander-picker"
  service = "drive.googleapis.com"
}

output "sheets_sa_email" {
  description = "The email of the Sheets Service Account"
  value       = google_service_account.sheets_sa.email
}
