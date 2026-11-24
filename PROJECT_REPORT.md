# DiseaseScope — Project Report

## 1. Project overview

DiseaseScope is a web-based analytics project for exploring disease-burden profiles and comparing unsupervised clustering results. It combines a React/Vite user interface with a Flask/Python analysis API. The project expects an IHME Global Burden of Disease 2023 extract, which is intentionally excluded from this repository, and includes a separate workflow for users to inspect and analyze their own tabular datasets.

The application is intended for educational and exploratory analysis. It is not a clinical tool and does not provide medical advice.

## 2. Goals and scope

The project aims to:

- Summarize the included disease-burden data by profile and feature.
- Group profiles with K-Means or hierarchical clustering.
- Visualize profiles in two dimensions using PCA.
- Compare selected country profiles and inspect cluster characteristics.
- Compare K-Means results across multiple cluster counts and present a recommended K.
- Allow the user to upload, inspect, preprocess, analyze, and export a separate dataset.

## 3. Dataset

The default source is an IHME GBD results ZIP configured through `DISEASESCOPE_DATA`; it is not tracked in this repository. Obtain it from IHME and follow the source terms and citation requirements. The archive used during development contains a CSV with 1,090 observations. The default pipeline filters for year 2023, both sexes, age-standardized DALY rates, pivots causes into location profiles, and drops incomplete profiles. That extract produces 109 complete location profiles across 10 cause categories.

The backend computes labels, metrics, and PCA coordinates at startup instead of relying on missing pre-exported analysis files. Uploaded data is processed separately and does not modify the source archive.

## 4. System design

### Frontend

The React application provides the landing page and the following workspace views:

1. **Dashboard** — dataset summary, cluster distribution, feature averages, and country/profile exploration.
2. **Clustering Analysis** — K-Means or hierarchical assignments, distributions, cluster-average profiles, filtering, and CSV export.
3. **PCA Visualization** — two-component projection colored by the chosen cluster assignments.
4. **Country Comparison** — compare selected profile values and assignments.
5. **Model Evaluation** — display K evaluation charts, a metric table, active/recommended K, and an action to apply the recommendation.
6. **Cluster Insights** — explore summarized cluster characteristics.
7. **Upload Dataset** — inspect and analyze a user-provided file.

The Vite development server proxies API requests from `/api` to Flask on port 5000. The frontend keeps the active upload ID and any applied cluster count in `sessionStorage`, scoped to the current browser tab. Separate tabs and datasets therefore keep independent selections.

### Backend

`backend/app.py` loads and analyzes the configured default archive, exposes the shared dashboard APIs, validates active cluster counts, and serves consistent cluster results. `backend/upload_service.py` implements isolated in-memory upload handling, quality inspection, preprocessing, analysis, and downloads.

The backend's active-K parameter is used to calculate consistent K-Means and Ward assignments for the selected count. On the frontend, applying the recommendation triggers fresh API requests; simply viewing the recommendation does not change the active model.

## 5. Analysis methodology

### Default dataset

The disease-category features are standardized using scikit-learn `StandardScaler`. The configured starting K is six. K-Means uses Euclidean distance, a fixed random seed, and multiple initializations. The hierarchical model uses Ward linkage. PCA is fit to the same standardized feature matrix and projected into two components.

### Uploaded dataset

The upload workflow starts by selecting numeric candidate columns and excluding likely ID/year columns. Its default analysis uses median imputation, standardization, K-Means, and up to four clusters. It requires at least three rows and two model features. The API also supports selecting features, removing duplicates, other missing-value strategies, categorical one-hot encoding, turning standardization off, and choosing hierarchical clustering. Country/location labels are excluded from model features.

### Multiple K evaluation

The evaluation procedure fits K-Means for K=2 through K=10 where the dataset permits (K is capped at N-1 for N profiles). For each candidate, it records:

- **WCSS** (within-cluster sum of squares / K-Means inertia), used by the Elbow Method.
- **Silhouette Score**, using Euclidean distance.
- **Davies–Bouldin Index**.

The three evaluation visualizations and results table are calculated from the active dataset's analyzed feature matrix. For larger datasets, silhouette uses a deterministic sample of up to 2,000 rows. A valid K must produce at least two, but fewer than N, distinct labels.

A larger Silhouette Score and smaller Davies–Bouldin Index generally indicate better-separated clusters. The Elbow Method is a complementary criterion that looks for diminishing reduction in WCSS as K increases. DiseaseScope forms a recommendation from equal-weight ranks of the two metric scores and adds a one-rank preference to the detected elbow K; ties favor smaller K. The recommended value is advisory and does not replace the active K until the user applies it.

## 6. API summary

Core dashboard endpoints:

| Endpoint | Function |
|---|---|
| `GET /api/health` | Confirm backend health. |
| `GET /api/summary`, `GET /api/countries` | Retrieve the dataset summary and available profile names. |
| `GET /api/countries/<country>` | Retrieve an individual profile and its cluster information. |
| `GET /api/clusters` | Retrieve assignments, distribution, and average feature profiles. |
| `GET /api/pca` | Retrieve PCA coordinates and cluster labels. |
| `GET /api/evaluation` | Retrieve active-model metrics and multiple-K evaluation results. |
| `GET /api/compare` | Compare selected profiles. |

The dashboard endpoints accept optional `dataset_id` and `active_k` query parameters. Upload endpoints under `/api/uploads` provide upload, inspection, preprocessing preview, analysis, result retrieval, profile search, exports, and deletion. The API request/response details are maintained in the project [README](./README.md#api-reference).

## 7. Data handling, constraints, and errors

- Accepted upload formats: CSV, XLSX, XLS, or ZIP containing exactly one supported data file.
- Upload limits: 20 MB compressed, 100 MB expanded, 50,000 rows, and 100 columns.
- Clustering is limited to 5,000 rows per upload analysis to bound hierarchical clustering and pairwise metric costs.
- At most eight temporary uploads are held concurrently; upload records expire after one hour and are cleared when the Flask process restarts.
- Invalid algorithm names, malformed or out-of-range K values, insufficient sample counts, invalid features, and missing values that remain after preprocessing are rejected with an error response.
- Uploaded original files are kept in memory; analysis data is not written into the included IHME archive. The original download preserves uploaded bytes.
- Processed CSV exports prefix formula-leading text with an apostrophe to reduce spreadsheet formula-injection risk.

## 8. Running and testing

Install backend dependencies from the project root:

```powershell
python -m pip install -r backend\requirements.txt
```

Start Flask in one terminal:

```powershell
python backend\app.py
```

Install and start Vite in another terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open the local URL printed by Vite, normally `http://localhost:5173`. Run backend tests from the project root with:

```powershell
python -m unittest discover -s backend -p "test_*.py"
```

Build the frontend production bundle from the `frontend` directory with `npm run build`.

## 9. Limitations and interpretation

The default results reflect only the supplied extract and the filters used by the application. Uploaded analyses depend on user-selected features, missing-data strategy, standardization, and algorithm settings. Cluster numbers are arbitrary labels, and results may change when data or modeling settings change. PCA is a projection that can hide variation outside the first two components. Evaluation metrics summarize different aspects of cluster separation and should be considered together rather than treated as proof that one K is universally correct.

These aggregate-data analyses do not establish causation, define permanent country types, or support diagnosis or treatment decisions. Users should verify data provenance, scope, and preprocessing before interpreting the charts or metrics.

## 10. Source citation

Global Burden of Disease Collaborative Network. *Global Burden of Disease Study 2023 (GBD 2023) Results*. Seattle, United States: Institute for Health Metrics and Evaluation (IHME), 2024. [IHME GBD Results](https://vizhub.healthdata.org/gbd-results/).
