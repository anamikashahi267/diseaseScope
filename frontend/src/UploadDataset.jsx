import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, ArrowRight, Check, Database, FileSpreadsheet, Info,
  LoaderCircle, ShieldCheck, Trash2, Upload, X,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { API_BASE } from './api.js'
import './upload-dataset.css'

const MAX_FILE_SIZE = 20 * 1024 * 1024

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  const contentType = response.headers.get('content-type') || ''
  const result = contentType.includes('application/json') ? await response.json() : await response.blob()
  if (!response.ok) {
    const error = new Error(result.error || `Request failed (${response.status})`)
    error.status = response.status
    throw error
  }
  return result
}

function bytes(value) {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(2)} MB`
}

function Section({ title, subtitle, action, children, className = '' }) {
  return <section className={`upload-panel ${className}`}><div className="upload-panel-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}

function StatusNotice({ children, tone = 'info' }) {
  const Icon = tone === 'warning' ? AlertTriangle : tone === 'success' ? Check : Info
  return <div className={`upload-notice ${tone}`}><Icon size={17} />{children}</div>
}

export default function UploadDataset() {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [upload, setUpload] = useState(null)
  const [inspection, setInspection] = useState(null)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('idle')
  const [dragging, setDragging] = useState(false)
  const [features, setFeatures] = useState([])
  const [activeDatasetId, setActiveDatasetId] = useState(() => sessionStorage.getItem('diseasescope-active-dataset-id') || '')

  const updateActiveDataset = (datasetId, filename = '') => {
    if (datasetId) {
      sessionStorage.setItem('diseasescope-active-dataset-id', datasetId)
      sessionStorage.setItem('diseasescope-active-dataset-name', filename)
    } else {
      sessionStorage.removeItem('diseasescope-active-dataset-id')
      sessionStorage.removeItem('diseasescope-active-dataset-name')
    }
    setActiveDatasetId(datasetId)
    window.dispatchEvent(new Event('diseasescope-active-dataset-change'))
  }

  const clearDataset = async () => {
    if (upload?.dataset_id) {
      try {
        await request(`/uploads/${upload.dataset_id}`, { method: 'DELETE' })
      } catch (exception) {
        if (exception.status !== 404) {
          setError(`Could not remove the temporary upload: ${exception.message}`)
          return
        }
      }
    }
    sessionStorage.removeItem('diseasescope-upload-id')
    if (activeDatasetId === upload?.dataset_id) updateActiveDataset('')
    setUpload(null)
    setInspection(null)
    setFile(null)
    setError('')
    setStatus('idle')
    setFeatures([])
    if (inputRef.current) inputRef.current.value = ''
  }

  const loadExisting = async datasetId => {
    try {
      const details = await request(`/uploads/${datasetId}/inspection`)
      const restored = { dataset_id: datasetId, filename: details.filename, file_size: details.file_size }
      setUpload(restored)
      setInspection(details.inspection)
      setFeatures(details.inspection.numeric_candidates.filter(name => !/(^id$|_id$|^year$)/i.test(name)))
      setStatus(details.analysis_ready ? 'analyzed' : 'uploaded')
      if (details.analysis_ready && sessionStorage.getItem('diseasescope-active-dataset-id') === datasetId) {
        updateActiveDataset(datasetId, details.filename)
      }
    } catch (exception) {
      if (exception.status === 404) {
        sessionStorage.removeItem('diseasescope-upload-id')
        if (sessionStorage.getItem('diseasescope-active-dataset-id') === datasetId) updateActiveDataset('')
      } else {
        setError(`Could not restore the temporary upload: ${exception.message}`)
      }
    }
  }

  useEffect(() => {
    const savedId = sessionStorage.getItem('diseasescope-upload-id')
    if (savedId) loadExisting(savedId)
  }, [])

  const validateFile = candidate => {
    setError('')
    const extension = candidate.name.split('.').pop()?.toLowerCase()
    if (!['csv', 'xlsx', 'xls', 'zip'].includes(extension)) {
      setFile(null)
      setError('Unsupported file format. Choose a .csv, .xlsx, .xls, or .zip file.')
      return
    }
    if (candidate.size > MAX_FILE_SIZE) {
      setFile(null)
      setError('The selected file is larger than the 20 MB limit.')
      return
    }
    setFile(candidate)
  }

  const submitUpload = async () => {
    if (!file) return
    setStatus('uploading')
    setError('')
    const form = new FormData()
    form.append('file', file)
    try {
      const data = await request('/uploads', { method: 'POST', body: form })
      if (upload?.dataset_id) {
        try {
          await request(`/uploads/${upload.dataset_id}`, { method: 'DELETE' })
        } catch (exception) {
          if (exception.status !== 404) throw exception
        }
      }
      if (activeDatasetId) updateActiveDataset('')
      setUpload({ dataset_id: data.dataset_id, filename: data.filename, file_size: data.file_size })
      setInspection(data.inspection)
      setStatus('uploaded')
      setFeatures(data.inspection.numeric_candidates.filter(name => !/(^id$|_id$|^year$)/i.test(name)))
      sessionStorage.setItem('diseasescope-upload-id', data.dataset_id)
      setFile(null)
      if (inputRef.current) inputRef.current.value = ''
    } catch (exception) {
      setError(exception.message)
      setStatus(upload ? 'uploaded' : 'idle')
    }
  }

  const runAnalysis = async () => {
    if (!upload || features.length < 2 || inspection.rows < 3) return
    setError('')
    setStatus('analyzing')
    const options = {
      remove_duplicates: false,
      missing_strategy: 'median',
      features,
      categorical_features: [],
      standardize: true,
      algorithm: 'kmeans',
      n_clusters: Math.min(4, inspection.rows - 1),
    }
    try {
      await request(`/uploads/${upload.dataset_id}/preview`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      })
      await request(`/uploads/${upload.dataset_id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(options),
      })
      setStatus('analyzed')
      updateActiveDataset(upload.dataset_id, upload.filename)
    } catch (exception) {
      setError(exception.message)
      setStatus('uploaded')
    }
  }

  const onDrop = event => {
    event.preventDefault()
    setDragging(false)
    const candidate = event.dataTransfer.files?.[0]
    if (candidate) validateFile(candidate)
  }

  const useDefaultDataset = () => {
    updateActiveDataset('')
  }

  return <div className="upload-page">
    <div className="page-title">
      <div>
        <div className="eyebrow">WORKSPACE / DATA TOOLS</div>
        <h1>Upload a dataset</h1>
        <p>Choose the included IHME dataset or upload your own file, then run an analysis.</p>
      </div>
      <div className="upload-private"><ShieldCheck size={15} /> Private to this browser session</div>
    </div>

    <StatusNotice>CSV, Excel, and ZIP files with one supported dataset are accepted. Uploads are temporary, isolated from the IHME data, and limited to 20 MB. ZIP archives may expand to 100 MB.</StatusNotice>
    {error && <div className="upload-error"><AlertTriangle size={17} /><div><b>Could not complete the request</b><span>{error}</span></div><button onClick={() => setError('')} aria-label="Dismiss error"><X size={15} /></button></div>}

    <Section
      title="Default dataset"
      subtitle="The supplied IHME Global Burden of Disease 2023 dataset is ready to use."
      className="default-dataset-panel"
      action={activeDatasetId && <button className="button button-outline button-small" onClick={useDefaultDataset}>Use default dataset</button>}
    >
      <div className="default-dataset-file">
        <span className="uploaded-file-icon"><Database size={19} /></span>
        <div><b>IHME-GBD_2023_DATA-f03f1508-1.zip</b><span>2023 · Both sexes · Age-standardized DALY rate · 109 country/location profiles</span></div>
        <span className="upload-complete"><Check size={14} /> {activeDatasetId ? 'Available' : 'Selected'}</span>
      </div>
      <div className="default-dataset-footer">
        <span>{activeDatasetId ? 'Switch back to the included dataset at any time.' : 'The included dataset is the current data source.'}</span>
        <Link className="button button-outline button-small" to="/dashboard">Open dashboard <ArrowRight size={13} /></Link>
      </div>
    </Section>

    <Section
      title="Upload your dataset"
      subtitle="Select or drop a CSV, Excel workbook, or ZIP archive."
      action={upload && <button className="button button-danger button-small" onClick={clearDataset}><Trash2 size={14} /> Remove upload</button>}
    >
      {upload && inspection && <>
        <div className="uploaded-file">
          <span className="uploaded-file-icon"><FileSpreadsheet size={19} /></span>
          <div className="uploaded-file-name"><b>{upload.filename}</b><span>{bytes(upload.file_size)} · Private temporary session</span></div>
          <span className="upload-complete"><Check size={14} /> {status === 'analyzed' ? 'Analysis complete' : 'Ready to analyze'}</span>
        </div>
        <div className="upload-actions">
          <span>{status === 'analyzing' ? 'Analyzing your dataset…' : status === 'analyzed' ? 'Your uploaded dataset is active across the dashboard.' : `${inspection.rows.toLocaleString()} rows · ${features.length} numeric features selected`}</span>
          <button className="button button-primary" disabled={features.length < 2 || inspection.rows < 3 || status === 'analyzing' || status === 'uploading'} onClick={runAnalysis}>
            {status === 'analyzing' ? <LoaderCircle size={15} className="spin" /> : <ArrowRight size={15} />}
            {status === 'analyzing' ? 'Running analysis…' : status === 'analyzed' ? 'Run analysis again' : 'Run analysis'}
          </button>
        </div>
        {(features.length < 2 || inspection.rows < 3) && <div className="upload-inline-notice"><Info size={15} /> Clustering requires at least three rows and two numeric features.</div>}
        {status === 'analyzed' && <StatusNotice tone="success">Analysis finished. Open the dashboard and other pages to explore your uploaded dataset.</StatusNotice>}
        {status === 'analyzed' && activeDatasetId !== upload.dataset_id && <button className="button button-outline button-small" onClick={() => updateActiveDataset(upload.dataset_id, upload.filename)}>Use across app</button>}
      </>}

      <div
        className={`upload-dropzone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
        onDragOver={event => { event.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click() }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls,.zip,text/csv,application/zip,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={event => event.target.files?.[0] && validateFile(event.target.files[0])}
          hidden
        />
        <span className="drop-icon"><Upload size={23} /></span>
        <b>{file ? file.name : upload ? 'Drop a new dataset to replace this upload' : 'Drop your dataset here'}</b>
        <span>{file ? `${bytes(file.size)} · Ready to upload` : 'or browse files from your device'}</span>
        <small>CSV · XLSX · XLS · ZIP</small>
      </div>
      {file && <div className="chosen-file"><FileSpreadsheet size={17} /><div><b>{file.name}</b><span>{bytes(file.size)} · Ready</span></div><button className="icon-button" onClick={event => { event.stopPropagation(); setFile(null); if (inputRef.current) inputRef.current.value = '' }} aria-label="Remove selected file"><X size={16} /></button></div>}
      <div className="upload-actions">
        <span>{status === 'uploading' ? 'Uploading and checking your file…' : upload ? 'The current upload stays available until its replacement finishes.' : 'Your original file is not modified.'}</span>
        <button className="button button-primary" disabled={!file || status === 'uploading'} onClick={submitUpload}>
          {status === 'uploading' ? <LoaderCircle size={15} className="spin" /> : <Upload size={15} />}
          {status === 'uploading' ? 'Uploading…' : upload ? 'Upload and replace' : 'Upload dataset'}
        </button>
      </div>
    </Section>

    <div className="upload-bottom-note"><ShieldCheck size={15} /> Uploaded files stay in temporary server memory for this session and expire after one hour.</div>
  </div>
}
