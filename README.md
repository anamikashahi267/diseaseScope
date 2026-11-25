# DiseaseScope — Global Disease Burden Analytics

DiseaseScope is a React dashboard and Flask API for exploring disease-burden profiles, comparing clustering methods, and analyzing a user-provided tabular dataset. It is an exploratory analytics tool, not a medical decision-support system.

## Contents

- [Features](#features)
- [Data and methodology](#data-and-methodology)
- [Requirements and setup](#requirements-and-setup)
- [Run the application](#run-the-application)
- [Configure the default-data archive](#configure-the-default-data-archive)
- [Project structure](#project-structure)
- [API reference](#api-reference)
- [Dataset upload and limits](#dataset-upload-and-limits)
- [Tests and production build](#tests-and-production-build)
- [Troubleshooting](#troubleshooting)
- [Limitations and responsible use](#limitations-and-responsible-use)
- [Citation](#citation)

## Features

- Dashboard with dataset summary, cluster distribution, leading feature averages, and a country/profile explorer.
- K-Means and hierarchical clustering views, cluster assignments, feature profiles, and CSV export.
- Two-component PCA visualization, colored by the selected clustering algorithm.
- Country comparison and cluster insights.
- Model evaluation across K values, with WCSS (Elbow Method), Silhouette Score, Davies–Bouldin Index, a results table, and a dynamically calculated recommended K.
- An **Apply Recommended K** action. The active count is not changed unless the user applies the recommendation. An applied count is kept separately for each browser tab and dataset.
- A dataset upload workflow for inspecting data, previewing preprocessing, running analysis, and downloading results and reports.

## Data and methodology

The default analysis expects the `IHME-GBD_2023_DATA-f03f1508-1.zip` archive, which is intentionally not tracked in this repository. Obtain the data through IHME and follow its terms of use and citation requirements. The archive contains one CSV with 1,090 observations. For the default analysis, the backend selects 2023, both-sex, age-standardized DALY rates; pivots causes into location profiles; and drops incomplete profiles. The supplied extract currently yields 109 complete locations and 10 cause categories.

The project does not depend on exported Colab cluster labels, PCA coordinates, profiles, or evaluation scores. It computes its results from the source data when Flask starts. Results can differ from another analysis if that analysis used different data, filters, preprocessing, or model parameters.

Default-dataset feature values are standardized with scikit-learn `StandardScaler`. The configured starting cluster count is six. K-Means uses Euclidean distance and a fixed random seed; hierarchical clustering uses Ward linkage. PCA projects the same standardized feature matrix into two components.

For model selection, K-Means is evaluated for K=2 through K=10, limited to at most one less than the number of available profiles. WCSS is the K-Means inertia. Silhouette uses Euclidean distance; Davies–Bouldin is calculated from the same model labels. For larger datasets, silhouette is calculated on a deterministic sample of up to 2,000 profiles. Higher Silhouette and lower Davies–Bouldin scores indicate better-separated clusters. The Elbow Method provides an additional criterion. The recommendation combines equal-weight ranks of the two comparison metrics and gives the detected elbow a one-rank preference; ties favor smaller K. It is a guide, not an automatic model change.

Once applied, the active K is used consistently for K-Means and Ward cluster assignments, distributions, profiles, country detail/comparison, PCA point colors, and insights. Other tabs and datasets retain their own selection. Uploaded analyses use the selected preprocessing options and feature matrix, so they may differ from the default-data pipeline.

## Requirements and setup

- Python with the packages listed in `backend\requirements.txt`.
- Node.js and npm, for the Vite/React frontend.
- An IHME GBD results ZIP archive for the default dashboard dataset; keep it outside the repository and set `DISEASESCOPE_DATA` as described below.

Open PowerShell in the project root and install the backend packages:

```powershell
python -m pip install -r backend\requirements.txt
```

In another PowerShell terminal, install frontend packages:

```powershell
Set-Location frontend
npm install
```

## Run the application

Start the backend from the project root:

```powershell
$env:DISEASESCOPE_DATA = "C:\path\to\IHME-GBD_2023_DATA-f03f1508-1.zip"
python backend\app.py
```

Download the archive from [IHME GBD Results](https://vizhub.healthdata.org/gbd-results/) and save it outside the repository. Set `DISEASESCOPE_DATA` to its path in the same terminal used to start Flask. Flask listens on `http://127.0.0.1:5000` by default. In a second terminal, start the frontend:

```powershell
Set-Location .\frontend
npm run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). Vite proxies `/api` requests to Flask on port 5000. Keep both terminals running while using the app; stop either server with **Ctrl+C** in its terminal.

For the Render deployment, set the frontend service's `VITE_API_URL` environment variable to `https://diseasescope-2.onrender.com`. The frontend appends `/api` to this backend origin; when building for production without that variable, it defaults to the same Render backend. Vite embeds environment values at build time, so redeploy the frontend after changing the variable. Flask allows the deployed frontend origin and localhost development origins for API requests.

## Configure the default-data archive

The IHME archive is excluded from Git. Set `DISEASESCOPE_DATA` in the same PowerShell terminal used to start Flask:

```powershell
$env:DISEASESCOPE_DATA = "C:\path\to\gbd-results.zip"
python backend\app.py
```

The archive must contain a CSV with the columns and GBD values expected by the default analysis. This setting changes the default source file; it does not change the separate upload workflow.

## Project structure

| Path | Purpose |
|---|---|
| `backend\app.py` | Loads and analyzes the default archive; serves the dashboard, clustering, PCA, country, comparison, and evaluation APIs. |
| `backend\upload_service.py` | Validates and inspects uploads; previews preprocessing; runs clustering, PCA, metrics, and exports. |
| `backend\test_evaluation.py` | Focused tests for the K-Means evaluation calculations and invalid inputs. |
| `backend\requirements.txt` | Python backend dependencies. |
| `frontend\src\App.jsx` | Landing page, dashboard, explorer, clustering, PCA, comparison, evaluation, and insights pages. |
| `frontend\src\UploadDataset.jsx` | Dataset upload, inspection, preprocessing, and analysis interface. |
| `frontend\src\styles.css` and `frontend\src\upload-dataset.css` | Application and upload-page styles. |
| `frontend\vite.config.js` | Vite configuration and local `/api` proxy to Flask. |
| `PROJECT_REPORT.md` | Project overview, design, methodology, API summary, and limitations. |

## API reference

The dashboard API accepts optional `dataset_id=<temporary upload ID>` and `active_k=<count>` query parameters where relevant. Without `dataset_id`, endpoints use the configured default archive. The frontend adds these parameters for the selected upload and applied cluster count.

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Backend health and default archive name. |
| `GET /api/summary` | Profile, feature, dataset, and active-cluster summary. |
| `GET /api/countries` | Country/profile names. |
| `GET /api/countries/<country>` | Feature profile and cluster assignments for one country. |
| `GET /api/clusters?algorithm=<kmeans-or-hierarchical>` | Assignments, cluster distribution, and average feature profiles. |
| `GET /api/pca?algorithm=<kmeans-or-hierarchical>&cluster=<all-or-number>` | PCA coordinates and selected algorithm's cluster labels. |
| `GET /api/evaluation` | Active-model metrics and K-Means WCSS, Silhouette, Davies–Bouldin, elbow, and recommendation data. |
| `GET /api/compare?country=<name>&country=<name>` | Compare two to eight country profiles and their cluster assignments. |
| `POST /api/uploads` | Upload a CSV, Excel file, or ZIP containing one supported data file (`multipart` field `file`). |
| `GET /api/uploads/<id>/inspection` | Inspect an upload and report whether it has been analyzed. |
| `POST /api/uploads/<id>/preview` | Preview selected preprocessing options (JSON body). |
| `POST /api/uploads/<id>/analyze` | Run clustering, PCA, and metrics (JSON body). |
| `GET /api/uploads/<id>/results` | Retrieve the analyzed report, assignments, profiles, and visual summaries. |
| `GET /api/uploads/<id>/countries?q=<text>` | Search analyzed upload profiles. |
| `GET /api/uploads/<id>/country-profile?row=<number>` | Retrieve a profile by its one-based row number. |
| `GET /api/uploads/<id>/export/<kind>` | Download original data, processed CSVs, quality report, or JSON analysis report. |
| `DELETE /api/uploads/<id>` | Remove one temporary upload and its results. |

Supported export kinds are `original`, `cleaned`, `quality-report`, `assignments`, `profiles`, `pca`, `metrics`, and `report`.

## Dataset upload and limits

The Upload dataset page accepts CSV, XLSX, XLS, and ZIP files. A ZIP must contain exactly one supported dataset file; the first worksheet of an Excel workbook is analyzed. The upload is parsed in memory and does not modify or mix with the supplied IHME archive.

Limits are 20 MB per uploaded file, 100 MB expanded ZIP size, 50,000 rows, 100 columns, 5,000 rows for clustering, and eight concurrent temporary uploads. Upload records expire after one hour and are cleared when the backend restarts. The upload workflow requires at least three rows and two model features.

The default upload workflow automatically selects numeric candidate columns (excluding ID/year-like fields), imputes missing selected values with the median, standardizes features, and starts with up to four clusters. The API also supports preprocessing previews, optional duplicate removal, missing-value strategies, categorical one-hot encoding, standardization choice, and either K-Means or hierarchical clustering.

Country/location labels are not model features. Silhouette calculations use a deterministic sample of up to 2,000 rows for larger uploads. The original download preserves the uploaded bytes. Processed CSV exports protect against spreadsheet-formula-leading text. Quality and analysis reports are JSON.

## Tests and production build

From the project root, run the backend evaluation tests:

```powershell
python -m unittest discover -s backend -p "test_*.py"
```

Build the frontend production bundle:

```powershell
Set-Location frontend
npm run build
```

## Troubleshooting

- **Dataset unavailable:** Obtain the IHME ZIP and set `DISEASESCOPE_DATA` to its path in the Flask terminal before starting the backend.
- **API connection failure:** Check that Flask is listening on port 5000 and the frontend was started with `npm run dev`. The Vite proxy targets `http://127.0.0.1:5000`.
- **Upload disappeared:** Uploads are in-memory and expire after an hour or when Flask restarts. Upload and analyze the file again.
- **Invalid cluster count:** For a dataset with N analyzed profiles, `active_k` must be an integer from 2 through N-1.
- **Upload analysis rejected:** Check that selected columns contain usable values, at least two model features and three rows remain after preprocessing, and the analysis does not exceed the 5,000-row limit.

## Limitations and responsible use

The default analysis covers only the supplied extract and its selected 2023 both-sex, age-standardized DALY-rate records. Upload analysis is limited to the data and features selected by the user. Standardization, missing-value handling, and feature choices influence clustering and PCA results. Cluster IDs are arbitrary labels, not rankings or stable disease classifications.

These are exploratory groupings of aggregate rates. They do not establish causation, define permanent country types, or provide diagnosis or treatment advice. Review the source, scope, preprocessing choices, and metric trade-offs before interpreting results.

## Citation

Global Burden of Disease Collaborative Network. *Global Burden of Disease Study 2023 (GBD 2023) Results*. Seattle, United States: Institute for Health Metrics and Evaluation (IHME), 2024. Available from [IHME GBD Results](https://vizhub.healthdata.org/gbd-results/).
