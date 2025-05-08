# MTG Commander Picker

A full-stack web application to help Magic: The Gathering players randomly draft and reserve a Commander from a pre-defined Google Sheet of cards. The app picks three cards of each color for a user to choose from; the chosen card is marked as reserved and the others return to the stack for future picks. Players end up with one Commander per color (5 cards total).

---

## Table of Contents

* [Features](#features)
* [Repository Structure](#repository-structure)
* [Prerequisites](#prerequisites)
* [Setup](#setup)

  * [Google Sheets Integration](#google-sheets-integration)
  * [Environment Variables](#environment-variables)
  * [Fly.io Configuration](#flyio-configuration)
* [Development](#development)

  * [Frontend (React)](#frontend-react)
  * [Backend (Flask)](#backend-flask)
* [Docker](#docker)

  * [Build & Run Locally](#build--run-locally)
* [Deployment](#deployment)

  * [GitHub Actions CI/CD](#github-actions-cicd)
  * [Fly.io](#flyio)
* [Optional: GCP Terraform](#optional-gcp-terraform)
* [License](#license)

---

## Features

* Randomly sample 3 cards per color (White, Blue, Black, Red, Green)
* User picks one Commander per color
* Backend marks the chosen card as reserved in Google Sheets
* Unchosen cards return to the pool for other players
* Full-stack: React frontend + Flask API
* Single Docker container hosts both frontend & backend
* Hosted on Fly.io with automated CI/CD via GitHub Actions

---

## Repository Structure

```
mtg-commander-picker/
├── frontend/                # React application
│   ├── public/              # Public assets & index.html
│   ├── src/                 # React components & entrypoint
│   ├── package.json
│   └── postcss.config.js    # Tailwind CSS config
├── backend/                 # Flask API
│   ├── app.py               # Main application server
│   ├── pyproject.toml       # Poetry dependencies
│   └── poetry.lock
├── .github/
│   └── workflows/ci.yml     # GitHub Actions CI/CD pipeline
├── Dockerfile               # Root multi-stage build (frontend + backend)
├── fly.toml                 # Fly.io configuration
├── main.tf                  # (Optional) Terraform for GCP resources
└── README.md                # This file
```

---

## Prerequisites

* **Node.js** (v18+) & **npm** for frontend builds
* **Python** (>=3.13) & **Poetry** for backend dependencies
* **Docker** for container builds
* **flyctl** CLI for Fly.io deployment
* **Google account** with a service account for Sheets API
* (Optional) **Terraform** & **GCP project** if using `main.tf`

---

## Setup

### Google Sheets Integration

1. Create a new Google Sheet and populate your card list with columns:

   * `Card Name` (or `Name`)
   * `Color` (White, Blue, Black, Red, Green)
   * `Status` (blank or "reserved")
   * `Reserved By` (player name)
2. Enable the **Google Sheets API** in your Google Cloud project.
3. Create a **Service Account** and generate a JSON key.
4. Share your sheet with the service account email (e.g., `my-svc-account@...gserviceaccount.com`).

### Environment Variables

Set the following secrets (locally or in Fly/GitHub Actions):

* **`GOOGLE_SHEETS_CREDENTIALS_JSON`**: The full JSON key contents of your service account.
* **`GOOGLE_SHEET_ID`**: The ID of your Google Sheet (from the URL).
* **`ADMIN_SECRET`**: A passphrase used to authorize `/api/reset` requests.
* **`FLY_API_TOKEN`**: (for GitHub Actions) generated via `flyctl auth token`.

### Fly.io Configuration

1. Install `flyctl` and log in:

   ```bash
   flyctl auth login
   ```
2. Create or link your Fly app:

   ```bash
   flyctl launch --name mtg-commander-picker --dockerfile Dockerfile
   ```
3. Set runtime secrets:

   ```bash
   fly secrets set \
     GOOGLE_SHEETS_CREDENTIALS_JSON="$(cat service-account.json)" \
     GOOGLE_SHEET_ID="<your-sheet-id>" \
     ADMIN_SECRET="<your-admin-secret>"
   ```

---

## Development

### Frontend (React)

```bash
cd frontend
npm ci
npm start
```

* The dev server runs on `http://localhost:3000` and proxies `/api` to the Flask backend.

### Backend (Flask)

```bash
cd backend
poetry install
poetry run python app.py
```

* The API runs on `http://localhost:8080` by default.
* Endpoints:

  * `GET /api/cards?color=<Color>`
  * `POST /api/select-card`
  * `POST /api/reset` (requires `X-Admin-Secret` header)

---

## Docker

### Build & Run Locally

```bash
# From repo root
docker build -t mtg-commander-picker .
docker run -p 8080:8080 \
  -e GOOGLE_SHEETS_CREDENTIALS_JSON="$(cat service-account.json)" \
  -e GOOGLE_SHEET_ID="<sheet-id>" \
  -e ADMIN_SECRET="<admin-secret>" \
  mtg-commander-picker
```

* Visit `http://localhost:8080` to see the React app.
* API under `http://localhost:8080/api`.

---

## Deployment

### GitHub Actions CI/CD

* **Build & Publish**: Builds Docker image and pushes to GitHub Container Registry (`ghcr.io/gofrolist/mtg-commander-picker`).
* **Deploy**: Uses `flyctl deploy --image ghcr.io/gofrolist/mtg-commander-picker:latest` to update Fly.io.
* Ensure `FLY_API_TOKEN` is set in repo secrets.

### Fly.io

After CI passes, Fly.io serves your container at `https://mtg-commander-picker.fly.dev` (or your custom domain).

---

## Optional: GCP Terraform

Your `main.tf` can provision:

* A **Service Account** for Sheets API.
* A **Secret Manager** entry holding the service account JSON.

Use `terraform apply` and then pull the secret into Fly with:

```bash
fly secrets set GOOGLE_SHEETS_CREDENTIALS_JSON="$(gcloud secrets versions access latest --secret mtg-sheets-creds)"
```

---

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for details.
