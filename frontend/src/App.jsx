import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate, NavLink, Outlet, Route, Routes, useLocation, useSearchParams } from 'react-router-dom'
import {
  Activity, ArrowDownToLine, ArrowRight, BarChart3, CalendarDays, Check,
  CircleHelp, Database, GitCompareArrows, Globe2, Layers3, Maximize2, Menu, Microscope,
  Search, ShieldCheck, Sparkles, Upload, X,
} from 'lucide-react'
import UploadDataset from './UploadDataset.jsx'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Radar, RadarChart,
  PolarAngleAxis, PolarGrid, PolarRadiusAxis, ResponsiveContainer, Scatter,
  ScatterChart, Tooltip, XAxis, YAxis,
} from 'recharts'

const API = '/api'
const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: BarChart3 },
  { to: '/clustering', label: 'Clustering analysis', icon: Layers3 },
  { to: '/pca', label: 'PCA visualization', icon: Activity },
  { to: '/comparison', label: 'Country comparison', icon: GitCompareArrows },
  { to: '/evaluation', label: 'Model evaluation', icon: ShieldCheck },
  { to: '/insights', label: 'Cluster insights', icon: Sparkles },
  { to: '/upload', label: 'Upload dataset', icon: Upload },
]
const COLORS = ['#0f766e', '#2563eb', '#e59b43', '#7856c7', '#df6c68', '#397e9c']
const short = (value, n = 20) => value?.length > n ? `${value.slice(0, n - 1)}…` : value

function readActiveDataset() {
  return {
    id: sessionStorage.getItem('diseasescope-active-dataset-id') || '',
    name: sessionStorage.getItem('diseasescope-active-dataset-name') || '',
  }
}

function useActiveDataset() {
  const [activeDataset, setActiveDataset] = useState(readActiveDataset)
  useEffect(() => {
    const refresh = () => setActiveDataset(readActiveDataset())
    window.addEventListener('diseasescope-active-dataset-change', refresh)
    return () => window.removeEventListener('diseasescope-active-dataset-change', refresh)
  }, [])
  return activeDataset
}

function activeClusterCountStorageKey(datasetId = sessionStorage.getItem('diseasescope-active-dataset-id')) {
  return `diseasescope-active-k-${datasetId || 'default'}`
}

function readActiveClusterCount() {
  return sessionStorage.getItem(activeClusterCountStorageKey()) || ''
}

function useActiveClusterCount() {
  const [activeClusterCount, setActiveClusterCount] = useState(readActiveClusterCount)
  useEffect(() => {
    const refresh = () => setActiveClusterCount(readActiveClusterCount())
    window.addEventListener('diseasescope-active-dataset-change', refresh)
    window.addEventListener('diseasescope-active-cluster-count-change', refresh)
    return () => {
      window.removeEventListener('diseasescope-active-dataset-change', refresh)
      window.removeEventListener('diseasescope-active-cluster-count-change', refresh)
    }
  }, [])
  return activeClusterCount
}

function applyActiveClusterCount(clusterCount) {
  sessionStorage.setItem(activeClusterCountStorageKey(), String(clusterCount))
  window.dispatchEvent(new Event('diseasescope-active-cluster-count-change'))
}

async function getData(path) {
  const activeDatasetId = sessionStorage.getItem('diseasescope-active-dataset-id')
  const params = new URLSearchParams()
  if (activeDatasetId) params.set('dataset_id', activeDatasetId)
  const activeClusterCount = readActiveClusterCount()
  if (activeClusterCount) params.set('active_k', activeClusterCount)
  const query = params.toString()
  const requestPath = query
    ? `${path}${path.includes('?') ? '&' : '?'}${query}`
    : path
  const response = await fetch(`${API}${requestPath}`)
  const data = await response.json()
  if (response.status === 410 && activeDatasetId) {
    sessionStorage.removeItem('diseasescope-active-dataset-id')
    sessionStorage.removeItem('diseasescope-active-dataset-name')
    window.dispatchEvent(new Event('diseasescope-active-dataset-change'))
    return getData(path)
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`)
  return data
}

function useResource(path, refresh = 0) {
  const [state, setState] = useState({ data: null, error: '', loading: true })
  const activeDataset = useActiveDataset()
  const activeClusterCount = useActiveClusterCount()
  useEffect(() => {
    if (!path) {
      setState({ data: null, error: '', loading: false })
      return undefined
    }
    let active = true
    setState({ data: null, error: '', loading: true })
    getData(path).then(data => active && setState({ data, error: '', loading: false }))
      .catch(error => active && setState({ data: null, error: error.message, loading: false }))
    return () => { active = false }
  }, [path, refresh, activeDataset.id, activeClusterCount])
  return state
}

function Loading() { return <div className="loading"><span className="spinner" /> Loading analysis…</div> }
function ErrorState({ error }) { return <div className="error-state"><CircleHelp size={18} /><div><b>Data unavailable</b><p>{error}. Check that the Flask API is running and the supplied archive is available.</p></div></div> }
function Notice({ children }) { return <div className="notice"><Activity size={17} />{children}</div> }
function PageTitle({ eyebrow, title, description, actions }) {
  return <div className="page-title"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="title-actions">{actions}</div>}</div>
}
function Panel({ title, subtitle, action, children, className = '' }) {
  return <section className={`panel ${className}`}><div className="panel-head"><div><h3>{title}</h3>{subtitle && <p>{subtitle}</p>}</div>{action}</div>{children}</section>
}
function Empty({ children }) { return <div className="empty">{children}</div> }
function MetricCard({ label, value, detail, icon: Icon, tone = 'teal' }) {
  return <div className="metric-card"><div className={`metric-icon ${tone}`}><Icon size={18} /></div><div className="metric-label">{label}</div><div className="metric-value">{value ?? '—'}</div><div className="metric-detail">{detail}</div></div>
}
function downloadCsv(filename, records) {
  if (!records?.length) return
  const columns = Object.keys(records[0])
  const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`
  const csv = [columns.map(quote).join(','), ...records.map(row => columns.map(key => quote(row[key])).join(','))].join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }))
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

function Shell() {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const activeDataset = useActiveDataset()
  useEffect(() => setOpen(false), [location.pathname])
  return <div className="app-shell">
    <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
      <Link to="/" className="brand"><span className="brand-mark"><Activity size={20} /></span><span>Disease<span className="brand-light">Scope</span><small>GLOBAL HEALTH ANALYTICS</small></span></Link>
      <div className="nav-caption">WORKSPACE</div>
      <nav>{NAV.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={17} /><span>{label}</span>{label === 'Dashboard' && <span className="nav-dot" />}</NavLink>)}</nav>
      <div className="sidebar-bottom"><div className="source-icon">{activeDataset.id ? <Database size={17} /> : <Globe2 size={17} />}</div><div><b>Data source</b><span title={activeDataset.name}>{activeDataset.id ? short(activeDataset.name || 'Uploaded dataset', 24) : 'IHME · GBD 2023'}</span></div><div className="status-dot" /></div>
    </aside>
    {open && <button className="scrim" onClick={() => setOpen(false)} aria-label="Close navigation" />}
    <div className="main-column">
      <header className="topbar"><button className="mobile-menu" onClick={() => setOpen(!open)} aria-label="Open navigation">{open ? <X size={20} /> : <Menu size={20} />}</button><div className="crumb"><span>Workspace</span><span>/</span><b>{NAV.find(item => item.to === location.pathname)?.label || 'Overview'}</b></div><div className="topbar-right"><span className="data-status"><i /> {activeDataset.id ? `Active upload · ${short(activeDataset.name || 'dataset', 20)}` : 'IHME · GBD 2023'}</span><span className="avatar">DS</span></div></header>
      <main className="content"><Outlet /></main>
      <footer className="site-footer"><span>Diseasescope <span className="footer-dot">·</span> Academic research project</span><span>Exploratory analysis only · Not medical advice</span></footer>
    </div>
  </div>
}

function ExplorerRedirect() {
  const [searchParams] = useSearchParams()
  const country = searchParams.get('country')
  const target = country ? `/dashboard?country=${encodeURIComponent(country)}#country-explorer` : '/dashboard#country-explorer'
  return <Navigate to={target} replace />
}

function Landing() {
  return <div className="landing">
    <header className="landing-nav">
      <Link to="/" className="brand"><span className="brand-mark"><Activity size={20} /></span><span>Disease<span className="brand-light">Scope</span><small>GLOBAL HEALTH ANALYTICS</small></span></Link>
      <nav className="landing-links" aria-label="Main navigation">
        <a href="#method">Explore</a>
        <a href="#project">About</a>
      </nav>
      <Link to="/dashboard" className="button button-primary">Open dashboard <ArrowRight size={15} /></Link>
    </header>
    <section className="hero">
      <div className="hero-copy">
        <div className="hero-tag"><span className="live-pulse" /> Global health intelligence</div>
        <h1>Understanding global disease burden <em>through machine learning.</em></h1>
        <p>Explore how countries’ disease-burden profiles compare. Discover statistical groupings, inspect the data, and question what the patterns can—and can’t—tell us.</p>
        <div className="hero-actions"><Link to="/dashboard" className="button button-primary">Explore dashboard <ArrowRight size={16} /></Link></div>
        <div className="hero-proof"><span><Check size={15} /> Research-focused analysis</span><span><Check size={15} /> Transparent methodology</span></div>
      </div>
      <div className="hero-visual">
        <img src="/diseasescope-landing-reference.png" alt="DiseaseScope global health analytics with a connected Earth, country map, cluster insights, and disease-burden trends" />
      </div>
    </section>
    <section className="landing-section" id="method"><div className="section-kicker">WHY CHOOSE DISEASESCOPE?</div><h2>Powerful insights. A healthier, more informed world.</h2><p className="section-lede">Explore global health patterns through an interactive, research-oriented lens.</p><div className="feature-grid"><Link className="home-feature-card" to="/evaluation"><div className="feature-icon"><BarChart3 size={19} /></div><div><h3>Advanced analytics</h3><p>Uncover patterns with machine learning.</p></div><ArrowRight size={17} /></Link><Link className="home-feature-card" to="/dashboard#country-explorer"><div className="feature-icon"><Globe2 size={19} /></div><div><h3>Global perspective</h3><p>Compare health profiles across countries.</p></div><ArrowRight size={17} /></Link><Link className="home-feature-card" to="/comparison"><div className="feature-icon"><Activity size={19} /></div><div><h3>Interactive insights</h3><p>Explore country profiles and comparisons.</p></div><ArrowRight size={17} /></Link><Link className="home-feature-card" to="/clustering"><div className="feature-icon"><ShieldCheck size={19} /></div><div><h3>Evidence-aware results</h3><p>Review methods, metrics, and limitations.</p></div><ArrowRight size={17} /></Link></div></section>
    <section className="landing-cta landing-about-project" id="project">
      <div className="landing-about-heading">
        <div className="section-kicker">ABOUT THIS PROJECT</div>
        <h2>How do countries’ health profiles compare?</h2>
        <p>This project studies patterns in disease-burden profiles using machine learning. It groups countries with similar profiles, then makes those patterns easier to inspect and compare through interactive visualizations.</p>
      </div>
      <div className="landing-project-steps">
        <article><span>01</span><div><b>Build profiles</b><p>Organize disease-burden measures into comparable country profiles.</p></div></article>
        <article><span>02</span><div><b>Find patterns</b><p>Use K-Means and hierarchical clustering to explore profile similarities.</p></div></article>
        <article><span>03</span><div><b>Explore results</b><p>Compare groups, view profiles, and inspect PCA and model evaluation.</p></div></article>
      </div>
      <div className="landing-about-footer"><span>These groupings are exploratory: they do not prove causation and are not medical advice.</span><Link to="/dashboard" className="button button-light">Explore the dashboard <ArrowRight size={16} /></Link></div>
    </section>
    <footer className="landing-footer"><Link to="/" className="brand"><span className="brand-mark"><Activity size={19} /></span><span>Disease<span className="brand-light">Scope</span></span></Link><span>Academic ML demonstration · No diagnosis or treatment advice</span></footer>
  </div>
}

function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams()
  const activeDataset = useActiveDataset()
  const { data, loading, error } = useResource('/summary')
  const cluster = useResource(data ? `/clusters?algorithm=${data.algorithm_key}` : '')
  const countryList = useResource('/countries')
  const [selectedProfile, setSelectedProfile] = useState(searchParams.get('country') || '')
  const [profileSearch, setProfileSearch] = useState('')
  const profile = useResource(selectedProfile ? `/countries/${encodeURIComponent(selectedProfile)}` : '')
  const [expandedChart, setExpandedChart] = useState('')
  useEffect(() => {
    if (countryList.data?.countries.length && !countryList.data.countries.includes(selectedProfile)) {
      const requestedProfile = searchParams.get('country')
      setSelectedProfile(countryList.data.countries.includes(requestedProfile) ? requestedProfile : countryList.data.countries[0])
    }
  }, [countryList.data, selectedProfile, searchParams])
  useEffect(() => {
    if (!expandedChart) return undefined
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = ''
    }
  }, [expandedChart])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const renderClusterChart = (height, chartKey = 'cluster-chart') => <ResponsiveContainer key={chartKey} width="100%" height={height}><BarChart data={cluster.data.distribution} margin={{ top: 8, right: 18, left: -12, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="cluster" tickFormatter={v => `Cluster ${v}`} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><YAxis allowDecimals={false} tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><Tooltip cursor={{ fill: '#f1f7f6' }} /><Bar dataKey="count" name="Profiles" radius={[6, 6, 0, 0]} isAnimationActive={false}>{cluster.data.distribution.map((row, i) => <Cell key={row.cluster} fill={COLORS[i % COLORS.length]} />)}</Bar></BarChart></ResponsiveContainer>
  const renderFeatureChart = (height, chartKey = 'feature-chart') => <ResponsiveContainer key={chartKey} width="100%" height={height}><BarChart data={data.top_causes} layout="vertical" margin={{ left: 22, right: 24, top: 8, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#edf1f3" /><XAxis type="number" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="cause" width={175} tickFormatter={v => short(v, 27)} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip formatter={v => Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 })} cursor={{ fill: '#f1f7f6' }} /><Bar dataKey="mean_rate" name="Mean value" fill="#168c82" radius={[0, 5, 5, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
  const expandAction = (key, label) => <button type="button" className="chart-expand-button" aria-label={`Expand ${label}`} title="Expand chart" onClick={event => { event.stopPropagation(); setExpandedChart(key) }}><Maximize2 size={14} /><span>Expand</span></button>
  const chartTarget = (key, label, content) => <div className="chart-expand-target" role="button" tabIndex={0} aria-label={`Click to expand ${label}`} onClick={() => setExpandedChart(key)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setExpandedChart(key) } }}>{content}</div>
  const filteredProfiles = (countryList.data?.countries || []).filter(name => name.toLowerCase().includes(profileSearch.trim().toLowerCase()))
  const selectProfile = name => {
    setSelectedProfile(name)
    if (name) setSearchParams({ country: name }, { replace: true })
    else setSearchParams({}, { replace: true })
  }
  return <>
    <PageTitle eyebrow="OVERVIEW / 01" title="Global burden dashboard" description={`A data-grounded snapshot of ${data.dataset}.`} actions={<a className="button button-primary" href="#country-explorer">Explore profiles <ArrowRight size={15} /></a>} />
    <Notice>{data.analysis_note}</Notice>
    <div className="metric-grid">
      <MetricCard label="Profiles" value={data.country_count} detail="Analyzed records" icon={Globe2} />
      <MetricCard label={activeDataset.id ? 'Selected features' : 'Disease categories'} value={data.cause_count} detail={activeDataset.id ? 'Features in the uploaded dataset' : 'Categories in the supplied file'} icon={Activity} tone="blue" />
      <MetricCard label="Active Cluster Count" value={data.active_cluster_count ?? data.cluster_count} detail={`Active K-Means model (K = ${data.active_cluster_count ?? data.cluster_count})`} icon={Layers3} tone="gold" />
      <MetricCard label="Active algorithm" value={data.algorithm} detail="Switch methods in Clustering" icon={Microscope} tone="purple" />
    </div>
    {cluster.loading || !cluster.data ? <Loading /> : cluster.error ? <ErrorState error={cluster.error} /> : <div className="chart-grid">
      <Panel title="Profiles by cluster" subtitle={`${cluster.data.algorithm} · Records per cluster`} action={expandAction('clusters', 'profiles by cluster')}>{chartTarget('clusters', 'profiles by cluster', renderClusterChart(260))}</Panel>
      <Panel title="Highest average feature values" subtitle={`Mean across analyzed profiles · ${data.data_scope}`} action={expandAction('features', 'average feature values')}>{chartTarget('features', 'average feature values', renderFeatureChart(260))}</Panel>
    </div>}
    <div id="country-explorer"><Panel title="Explore a country profile" subtitle="Select a country to inspect its feature values, cluster assignment, and cluster average.">
      {countryList.loading && <Loading />}
      {countryList.error && <ErrorState error={countryList.error} />}
      {countryList.data && <>
        <div className="dashboard-profile-controls">
          <div className="search-field"><Search size={15} /><input aria-label="Search dashboard country profiles" placeholder="Search countries…" value={profileSearch} onChange={event => setProfileSearch(event.target.value)} /></div>
          <select aria-label="Choose dashboard country profile" value={selectedProfile} onChange={event => selectProfile(event.target.value)}>
            {filteredProfiles.map(name => <option key={name} value={name}>{name}</option>)}
          </select>
        </div>
        {!filteredProfiles.length && <Empty>No country profiles match this search.</Empty>}
        {profile.loading && <Loading />}
        {profile.error && <ErrorState error={profile.error} />}
        {profile.data && <div className="dashboard-profile-preview">
          <div className="dashboard-profile-summary">
            <span className="country-avatar">{profile.data.country.slice(0, 1)}</span>
            <div><span className="eyebrow">{activeDataset.id ? 'SELECTED PROFILE' : 'COUNTRY PROFILE'}</span><h3>{profile.data.country}</h3><p>{profile.data.profile.length} analyzed {activeDataset.id ? 'features' : 'disease categories'}</p></div>
            <div className="dashboard-profile-cluster"><span>K-MEANS CLUSTER</span><b>{profile.data.clusters.kmeans}</b><small>{profile.data.cluster_size} profiles</small></div>
          </div>
          <div className="dashboard-profile-chart">
            <ResponsiveContainer width="100%" height={280}><BarChart data={profile.data.profile} margin={{ top: 8, right: 12, left: -12, bottom: 62 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="cause" angle={-30} textAnchor="end" interval={0} height={78} tickFormatter={value => short(value, 18)} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} /><YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={value => Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })} /><Legend /><Bar dataKey="rate" name={activeDataset.id ? profile.data.country : 'DALY rate'} fill="#168c82" radius={[4, 4, 0, 0]} /><Bar dataKey="cluster_average" name="Cluster average" fill="#b9d9e8" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer>
          </div>
          <div className="dashboard-profile-footer"><span>Cluster assignments are exploratory groupings, not permanent classifications.</span><Link className="button button-outline button-small" to={`/dashboard?country=${encodeURIComponent(profile.data.country)}#country-explorer`}>Open this profile <ArrowRight size={14} /></Link></div>
        </div>}
      </>}</Panel></div>
    {expandedChart && cluster.data && <div className="chart-modal-backdrop" role="presentation" onClick={event => { if (event.target === event.currentTarget) setExpandedChart('') }}>
      <section className="chart-modal" role="dialog" aria-modal="true" aria-labelledby="expanded-chart-title">
        <div className="chart-modal-head"><div><span className="eyebrow">INTERACTIVE CHART</span><h2 id="expanded-chart-title">{expandedChart === 'clusters' ? 'Profiles by cluster' : 'Highest average feature values'}</h2><p>Hover over the chart to inspect values. Close this view to return to the dashboard.</p></div><button className="chart-modal-close" aria-label="Close expanded chart" onClick={() => setExpandedChart('')}><X size={19} /></button></div>
        <div className="chart-modal-content">{expandedChart === 'clusters' ? renderClusterChart(540, 'expanded-cluster-chart') : renderFeatureChart(540, 'expanded-feature-chart')}</div>
      </section>
    </div>}
    <Panel title="Dataset at a glance" subtitle="The data used throughout this dashboard"><div className="data-glance"><div><span>Source</span><b>{data.source}</b></div><div><span>Data scope</span><b>{data.data_scope}</b></div><div><span>Features analyzed</span><b>{data.causes.join(', ')}</b></div><div><span>Dataset</span><b className="mono">{data.dataset}</b></div></div></Panel>
  </>
}

function AlgorithmToggle({ value, onChange }) { return <div className="segmented"><button className={value === 'kmeans' ? 'selected' : ''} onClick={() => onChange('kmeans')}>K-Means</button><button className={value === 'hierarchical' ? 'selected' : ''} onClick={() => onChange('hierarchical')}>Hierarchical</button></div> }

function Clustering() {
  const activeDataset = useActiveDataset()
  const [algorithm, setAlgorithm] = useState('kmeans')
  const { data, loading, error } = useResource(`/clusters?algorithm=${algorithm}`)
  const [query, setQuery] = useState('')
  const [selectedCluster, setSelectedCluster] = useState(null)
  const [page, setPage] = useState(1)
  const pageSize = 12
  useEffect(() => setPage(1), [query, selectedCluster, algorithm])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const normalizedQuery = query.trim().toLowerCase()
  const assignments = data.assignments
    .filter(row => (selectedCluster === null || row.cluster === selectedCluster) && row.country.toLowerCase().includes(normalizedQuery))
    .sort((a, b) => a.country.localeCompare(b.country))
  const pageCount = Math.max(1, Math.ceil(assignments.length / pageSize))
  const currentPage = Math.min(page, pageCount)
  const visibleAssignments = assignments.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const firstVisible = assignments.length ? (currentPage - 1) * pageSize + 1 : 0
  const lastVisible = Math.min(currentPage * pageSize, assignments.length)
  const causes = Object.keys(data.profiles[0] || {}).filter(key => !['cluster', 'countries'].includes(key))
  const profileChartData = causes.map(cause => ({
    cause,
    ...Object.fromEntries(data.profiles.map(profile => [`Cluster ${profile.cluster}`, profile[cause]])),
  }))
  return <>
    <PageTitle eyebrow="METHODS / 03" title="Clustering analysis" description="Review profile assignments and average feature values for each algorithm." actions={<AlgorithmToggle value={algorithm} onChange={setAlgorithm} />} />
    <Notice>Computed from the active dataset using the analyzed features and K = {data.cluster_count}. Ward linkage is used for hierarchical clustering.</Notice>
    <div className="cluster-count-grid">{data.distribution.map((item, i) => <button type="button" className={`cluster-count ${selectedCluster === item.cluster ? 'active' : ''}`} key={item.cluster} onClick={() => setSelectedCluster(selectedCluster === item.cluster ? null : item.cluster)} aria-pressed={selectedCluster === item.cluster}><span className="cluster-color" style={{ background: COLORS[(item.cluster - 1) % COLORS.length] }} /><span>Cluster {item.cluster}</span><b>{item.count}</b><small>{activeDataset.id ? 'profiles' : 'countries'} · click to filter</small></button>)}</div>
    <Panel title="Cluster average feature profiles" subtitle={`${data.algorithm} · Mean selected-feature values`}><ResponsiveContainer width="100%" height={360}><LineChart data={profileChartData} margin={{ top: 10, right: 18, left: -8, bottom: 72 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="cause" angle={-30} textAnchor="end" interval={0} height={92} tickFormatter={value => short(value, 18)} tick={{ fontSize: 9 }} axisLine={false} tickLine={false} /><YAxis tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip labelFormatter={value => value} formatter={(value, name) => [Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }), name]} /><Legend />{data.profiles.map((profile, i) => <Line key={profile.cluster} type="monotone" dataKey={`Cluster ${profile.cluster}`} name={`Cluster ${profile.cluster} (${profile.countries})`} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />)}</LineChart></ResponsiveContainer></Panel>
    <Panel title="Profile assignments" subtitle={`${assignments.length} of ${data.assignments.length} profiles${selectedCluster === null ? '' : ` · Cluster ${selectedCluster}`}`} action={<button className="button button-outline button-small" onClick={() => downloadCsv(`diseasescope-${algorithm}-assignments.csv`, data.assignments)}><ArrowDownToLine size={14} /> Export CSV</button>}>
      <div className="table-tools"><button className="button button-outline button-small" onClick={() => setSelectedCluster(null)} disabled={selectedCluster === null}>All clusters</button><div className="search-field compact"><Search size={15} /><input aria-label="Search profile assignments" placeholder="Search profiles…" value={query} onChange={e => setQuery(e.target.value)} /></div></div>
      {visibleAssignments.length ? <div className="table-scroll"><table><thead><tr><th>Profile</th><th>Cluster</th><th>Algorithm</th></tr></thead><tbody>{visibleAssignments.map(row => <tr key={row.country}><td><Link to={`/dashboard?country=${encodeURIComponent(row.country)}#country-explorer`}>{row.country}</Link></td><td><span className="cluster-pill" style={{ '--cluster-color': COLORS[(row.cluster - 1) % COLORS.length] }}>Cluster {row.cluster}</span></td><td>{data.algorithm}</td></tr>)}</tbody></table></div> : <Empty>No profiles match this search and cluster filter.</Empty>}
      <div className="assignment-pagination"><span>Showing {firstVisible}–{lastVisible} of {assignments.length} profiles</span><div><button className="button button-outline button-small" onClick={() => setPage(currentPage - 1)} disabled={currentPage === 1}>Previous</button><span>Page {currentPage} of {pageCount}</span><button className="button button-outline button-small" onClick={() => setPage(currentPage + 1)} disabled={currentPage === pageCount}>Next</button></div></div>
    </Panel>
  </>
}

function PCAView() {
  const activeDataset = useActiveDataset()
  const activeClusterCount = useActiveClusterCount()
  const [algorithm, setAlgorithm] = useState('kmeans')
  const [cluster, setCluster] = useState('all')
  const { data, loading, error } = useResource(`/pca?algorithm=${algorithm}&cluster=${cluster}`)
  useEffect(() => setCluster('all'), [activeClusterCount])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const groups = [...new Set(data.points.map(point => point.cluster))]
  return <>
    <PageTitle eyebrow="VISUALIZE / 04" title="PCA profile map" description="Project standardized feature profiles into two dimensions to visually inspect their relationships." actions={<AlgorithmToggle value={algorithm} onChange={setAlgorithm} />} />
    <div className="notice"><Activity size={17} /><span>Principal Component Analysis (PCA) compresses the standardized category profiles into a two-dimensional view. Proximity suggests similarity in this projection; it does not establish cause or clinical meaning.</span></div>
    <Panel title="Profiles in PCA space" subtitle={`Colored by ${data.algorithm} cluster · Hover a point to inspect its label and coordinates`} action={<select className="compact-select" value={cluster} onChange={e => setCluster(e.target.value)}><option value="all">All clusters</option>{groups.map(n => <option key={n} value={n}>Cluster {n}</option>)}</select>}>
      <ResponsiveContainer width="100%" height={500}><ScatterChart margin={{ top: 20, right: 28, left: 10, bottom: 20 }}><CartesianGrid strokeDasharray="3 3" stroke="#edf1f3" /><XAxis type="number" dataKey="component_1" name="Component 1" label={{ value: `PCA Component 1 (${(data.explained_variance[0] * 100).toFixed(1)}% variance)`, position: 'insideBottom', offset: -8 }} tick={{ fontSize: 10 }} /><YAxis type="number" dataKey="component_2" name="Component 2" label={{ value: `PCA Component 2 (${(data.explained_variance[1] * 100).toFixed(1)}% variance)`, angle: -90, position: 'insideLeft' }} tick={{ fontSize: 10 }} /><Tooltip cursor={{ strokeDasharray: '3 3' }} content={({ active, payload }) => active && payload?.length ? <div className="chart-tooltip"><b>{payload[0].payload.country}</b><span>Cluster {payload[0].payload.cluster}</span><span>PC1: {payload[0].payload.component_1.toFixed(3)}</span><span>PC2: {payload[0].payload.component_2.toFixed(3)}</span></div> : null} />{groups.map((group, i) => <Scatter key={group} name={`Cluster ${group}`} data={data.points.filter(point => point.cluster === group)} fill={COLORS[(group - 1) % COLORS.length]} />)}</ScatterChart></ResponsiveContainer>
    </Panel>
    <div className="pca-footnote"><span><b>Component 1</b> explains {(data.explained_variance[0] * 100).toFixed(1)}% of variance</span><span><b>Component 2</b> explains {(data.explained_variance[1] * 100).toFixed(1)}% of variance</span><span>{data.points.length} plotted {activeDataset.id ? 'profiles' : 'country profiles'}</span></div>
  </>
}

function CountryComparison() {
  const activeDataset = useActiveDataset()
  const [countries, setCountries] = useState([])
  const [selected, setSelected] = useState([])
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const list = useResource('/countries')
  const toggle = name => setSelected(current => current.includes(name) ? current.filter(item => item !== name) : current.length < 6 ? [...current, name] : current)
  const compare = async () => {
    setLoading(true); setError(''); setResult(null)
    try { setResult(await getData(`/compare?${selected.map(name => `country=${encodeURIComponent(name)}`).join('&')}`)) }
    catch (e) { setError(e.message) } finally { setLoading(false) }
  }
  const chartData = result?.countries?.[0]?.profile.map((row, i) => ({
    cause: short(row.cause, 18),
    ...Object.fromEntries(result.countries.map(country => [country.country, country.profile[i].rate])),
  })) || []
  const radarData = result?.countries?.[0]?.profile.map((row, i) => ({
    cause: short(row.cause, 15),
    ...Object.fromEntries(result.countries.map(country => [country.country, country.profile[i].rate])),
  })) || []
  return <>
    <PageTitle eyebrow="COMPARE / 05" title="Profile comparison" description="Compare two to six profiles feature by feature. Differences are descriptive, not medical interpretations." />
    <Panel title="Choose profiles" subtitle="Select at least two profiles from the active dataset"><div className="country-picker">{list.loading ? <Loading /> : list.error ? <ErrorState error={list.error} /> : list.data.countries.map(name => <button key={name} onClick={() => toggle(name)} className={`country-option ${selected.includes(name) ? 'picked' : ''}`}>{selected.includes(name) && <Check size={13} />}{name}</button>)}</div><div className="picker-footer"><span>{selected.length} selected · Up to 6 profiles</span><button className="button button-primary" disabled={selected.length < 2 || loading} onClick={compare}>{loading ? 'Comparing…' : 'Compare profiles'} <ArrowRight size={15} /></button></div></Panel>
    {error && <ErrorState error={error} />}
    {loading && <Loading />}
    {result && <><div className="comparison-badges">{result.countries.map((country, i) => <span key={country.country} style={{ '--cluster-color': COLORS[i] }}><i />{country.country}<small>K-Means {country.clusters.kmeans} · Hierarchical {country.clusters.hierarchical}</small></span>)}</div><div className="chart-grid"><Panel title="Side-by-side feature values" subtitle={activeDataset.id ? 'Observed selected-feature values' : 'Observed DALY rate by cause'}><ResponsiveContainer width="100%" height={370}><BarChart data={chartData} margin={{ top: 8, right: 12, left: -12, bottom: 70 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="cause" angle={-34} textAnchor="end" interval={0} height={88} tick={{ fontSize: 9 }} /><YAxis tick={{ fontSize: 10 }} /><Tooltip /><Legend />{result.countries.map((country, i) => <Bar key={country.country} dataKey={country.country} fill={COLORS[i]} radius={[3, 3, 0, 0]} />)}</BarChart></ResponsiveContainer></Panel><Panel title="Relative profile shape" subtitle={activeDataset.id ? 'Radar view · selected-feature values' : 'Radar view · values remain in DALY rate units'}><ResponsiveContainer width="100%" height={370}><RadarChart data={radarData} outerRadius="72%"><PolarGrid /><PolarAngleAxis dataKey="cause" tick={{ fontSize: 9 }} /><PolarRadiusAxis tick={{ fontSize: 9 }} />{result.countries.map((country, i) => <Radar key={country.country} name={country.country} dataKey={country.country} stroke={COLORS[i]} fill={COLORS[i]} fillOpacity={0.10} />)}<Legend /><Tooltip /></RadarChart></ResponsiveContainer></Panel></div><Panel title="Observed profile values" subtitle="Values for selected profiles and features" action={<button className="button button-outline button-small" onClick={() => downloadCsv('diseasescope-profile-comparison.csv', result.countries.flatMap(country => country.profile.map(row => ({ profile: country.country, feature: row.cause, value: row.rate, kmeans_cluster: country.clusters.kmeans, hierarchical_cluster: country.clusters.hierarchical }))))}><ArrowDownToLine size={14} /> Export CSV</button>}><div className="table-scroll"><table><thead><tr><th>Feature</th>{result.countries.map(country => <th key={country.country}>{country.country}</th>)}</tr></thead><tbody>{result.countries[0].profile.map((row, i) => <tr key={row.cause}><td>{row.cause}</td>{result.countries.map(country => <td key={country.country}>{country.profile[i].rate.toLocaleString(undefined, { maximumFractionDigits: 1 })}</td>)}</tr>)}</tbody></table></div></Panel></>}
  </>
}

function Evaluation() {
  const { data, loading, error } = useResource('/evaluation')
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const kmeansEvaluation = data.kmeans_evaluation
  const evaluationScores = kmeansEvaluation.scores
  const currentK = data.active_cluster_count ?? data.cluster_count
  const recommendedK = kmeansEvaluation.recommended_k
  return <>
    <PageTitle eyebrow="VALIDATE / 06" title="Model evaluation" description="Compare K-Means cluster counts using WCSS, Silhouette Score, and Davies–Bouldin Index on the active dataset." />
    <Notice>The active clustering uses K = {currentK}. The recommended count is calculated from the active dataset's processed feature matrix and only becomes active when applied.</Notice>
    <Panel title="Algorithm metric comparison" subtitle="Metrics are calculated on the active feature profiles"><div className="table-scroll"><table><thead><tr><th>Algorithm</th><th>Silhouette ↑</th><th>Silhouette · Manhattan ↑</th><th>Davies–Bouldin ↓</th></tr></thead><tbody>{data.metrics.map((row, index) => <tr key={`${row.algorithm}-${index}`}><td><b>{row.algorithm}</b></td><td>{row.silhouette == null ? '—' : row.silhouette.toFixed(4)}</td><td>{row.silhouette_manhattan == null ? '—' : row.silhouette_manhattan.toFixed(4)}</td><td>{row.davies_bouldin == null ? '—' : row.davies_bouldin.toFixed(4)}</td></tr>)}</tbody></table></div></Panel>
    <section className="evaluation-recommendation">
      <div className="evaluation-cluster-counts">
        <div className="evaluation-cluster-count active"><span className="eyebrow">ACTIVE CLUSTER COUNT</span><strong>K = {currentK}</strong></div>
        <div className="evaluation-cluster-count recommended"><span className="eyebrow">RECOMMENDED CLUSTER COUNT</span><strong>K = {recommendedK}</strong></div>
        <p>Recommendation combines Silhouette and Davies–Bouldin rankings, with the detected elbow as an additional criterion{kmeansEvaluation.elbow_k ? ` (elbow at K = ${kmeansEvaluation.elbow_k})` : ''}.</p>
        <button className="button button-primary" disabled={currentK === recommendedK || !evaluationScores.find(row => row.k === recommendedK)?.valid} onClick={() => applyActiveClusterCount(recommendedK)}>{currentK === recommendedK ? 'Recommended K is active' : 'Apply Recommended K'} <Check size={15} /></button>
      </div>
      <div className="evaluation-recommendation-detail"><b>{kmeansEvaluation.sample_count.toLocaleString()} profiles evaluated</b><span>Silhouette sample: {kmeansEvaluation.silhouette_sample_size.toLocaleString()}</span><span>Applying K updates assignments across the dashboard and analysis pages.</span></div>
    </section>
    {kmeansEvaluation.max_k_evaluated < 10 && <div className="context-note">This dataset has {kmeansEvaluation.sample_count} samples, so valid K-Means evaluations are limited to K = 2 through {kmeansEvaluation.max_k_evaluated} (K must be less than the sample count).</div>}
    <div className="chart-grid evaluation-chart-grid">
      <Panel title="Elbow Method" subtitle="WCSS (Euclidean) by K · look for the bend"><ResponsiveContainer width="100%" height={290}><LineChart data={evaluationScores} margin={{ top: 12, right: 18, left: 6, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="k" type="number" domain={['dataMin', 'dataMax']} tickCount={9} tick={{ fontSize: 10 }} label={{ value: 'K', position: 'insideBottom', offset: -3 }} /><YAxis tick={{ fontSize: 9 }} /><Tooltip formatter={value => value == null ? 'Unavailable' : Number(value).toFixed(2)} /><Line dataKey="wcss" name="WCSS" stroke="#168c82" strokeWidth={2.5} dot={{ fill: '#168c82', r: 4 }} connectNulls={false} /></LineChart></ResponsiveContainer></Panel>
      <Panel title="Silhouette Score" subtitle="Higher scores indicate better-separated clusters"><ResponsiveContainer width="100%" height={290}><LineChart data={evaluationScores} margin={{ top: 12, right: 18, left: 6, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="k" type="number" domain={['dataMin', 'dataMax']} tickCount={9} tick={{ fontSize: 10 }} label={{ value: 'K', position: 'insideBottom', offset: -3 }} /><YAxis domain={[-1, 1]} tick={{ fontSize: 9 }} /><Tooltip formatter={value => value == null ? 'Unavailable' : Number(value).toFixed(4)} /><Line dataKey="silhouette" name="Silhouette Score" stroke="#2563eb" strokeWidth={2.5} dot={{ fill: '#2563eb', r: 4 }} connectNulls={false} /></LineChart></ResponsiveContainer></Panel>
      <Panel title="Davies–Bouldin Index" subtitle="Lower values indicate more distinct clusters"><ResponsiveContainer width="100%" height={290}><LineChart data={evaluationScores} margin={{ top: 12, right: 18, left: 6, bottom: 8 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="k" type="number" domain={['dataMin', 'dataMax']} tickCount={9} tick={{ fontSize: 10 }} label={{ value: 'K', position: 'insideBottom', offset: -3 }} /><YAxis tick={{ fontSize: 9 }} /><Tooltip formatter={value => value == null ? 'Unavailable' : Number(value).toFixed(4)} /><Line dataKey="davies_bouldin" name="Davies–Bouldin Index" stroke="#c77928" strokeWidth={2.5} dot={{ fill: '#c77928', r: 4 }} connectNulls={false} /></LineChart></ResponsiveContainer></Panel>
    </div>
    <Panel title="K-Means evaluation by K" subtitle={`Same processed feature matrix · Euclidean K-Means · ${kmeansEvaluation.silhouette_sample_size.toLocaleString()}-profile silhouette sample`}><div className="table-scroll"><table><thead><tr><th>K</th><th>WCSS ↓</th><th>Silhouette Score ↑</th><th>Davies–Bouldin Index ↓</th></tr></thead><tbody>{evaluationScores.map(row => <tr key={row.k}><td><b>{row.k}{row.k === kmeansEvaluation.recommended_k ? ' · Recommended' : ''}</b></td><td>{row.wcss == null ? '—' : row.wcss.toFixed(4)}</td><td>{row.silhouette == null ? '—' : row.silhouette.toFixed(4)}</td><td>{row.davies_bouldin == null ? '—' : row.davies_bouldin.toFixed(4)}</td></tr>)}</tbody></table></div></Panel>
    <div className="definition-grid"><article><b>Silhouette score</b><p>Compares how close a profile is to its own cluster versus neighboring clusters. Higher values indicate better-separated groups; the score ranges from −1 to 1.</p></article><article><b>Davies–Bouldin index</b><p>Measures within-cluster scatter relative to separation between clusters. Lower values indicate more distinct groupings.</p></article><article><b>WCSS</b><p>Sum of squared Euclidean distances from points to their K-Means centroids. WCSS decreases as clusters are added; use the elbow as an additional criterion rather than choosing the lowest WCSS.</p></article></div>
    <div className="context-note">{kmeansEvaluation.selection_method} All K values use the same preprocessed feature matrix. Silhouette uses a deterministic sample of up to 2,000 profiles for larger datasets. Applying the recommendation changes the active clustering for this browser tab and dataset; it does not change the stored preprocessing or evaluation metrics.</div>
  </>
}

function Insights() {
  const activeDataset = useActiveDataset()
  const [algorithm, setAlgorithm] = useState('kmeans')
  const { data, loading, error } = useResource(`/clusters?algorithm=${algorithm}`)
  const [active, setActive] = useState(1)
  useEffect(() => {
    if (data?.profiles.length && !data.profiles.some(profile => profile.cluster === active)) {
      setActive(data.profiles[0].cluster)
    }
  }, [data, active])
  if (loading) return <Loading />
  if (error) return <ErrorState error={error} />
  const cluster = data.profiles.find(row => row.cluster === active)
  const causes = Object.keys(cluster || {}).filter(key => !['cluster', 'countries'].includes(key))
  const strongest = causes.map(cause => ({ cause, rate: cluster[cause] })).sort((a, b) => b.rate - a.rate).slice(0, 3)
  const assignment = data.assignments.filter(row => row.cluster === active).map(row => row.country)
  return <>
    <PageTitle eyebrow="INTERPRET / 07" title="Cluster insights" description="Explore cluster profiles as exploratory statistical summaries—not fixed classifications of countries." actions={<AlgorithmToggle value={algorithm} onChange={setAlgorithm} />} />
    <div className="notice"><Sparkles size={17} /><span>Cluster labels are arbitrary identifiers. Compare average rates within this dataset only; observed differences do not imply causation or explain health-system performance.</span></div>
    <div className="insight-layout">
      <div className="cluster-selector">{data.profiles.map((profile, i) => <button key={profile.cluster} className={active === profile.cluster ? 'chosen' : ''} onClick={() => setActive(profile.cluster)}><span className="cluster-color" style={{ background: COLORS[i] }} />Cluster {profile.cluster}<b>{profile.countries}</b><small>{activeDataset.id ? 'profiles' : 'countries'}</small></button>)}</div>
      <div className="insight-main">
        <div className="insight-head"><div className="cluster-large" style={{ background: COLORS[active - 1] }}>0{active}</div><div><span>{data.algorithm.toUpperCase()} · EXPLORATORY GROUP</span><h2>Cluster {active} profile</h2><p>{assignment.length} complete {activeDataset.id ? 'profiles' : 'country profiles'} in this cluster</p></div></div>
        <div className="strongest-grid">{strongest.map((item, i) => <div key={item.cause}><span>HIGHER MEAN FEATURE {i + 1}</span><b>{item.cause}</b><small>Average value: {item.rate.toLocaleString(undefined, { maximumFractionDigits: 1 })}</small></div>)}</div>
        <Panel title="Average feature values" subtitle={`Mean values for ${data.algorithm} cluster ${active}`}><ResponsiveContainer width="100%" height={330}><BarChart data={causes.map(cause => ({ cause: short(cause, 20), rate: cluster[cause] }))} margin={{ top: 8, right: 10, left: -10, bottom: 58 }}><CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf1f3" /><XAxis dataKey="cause" angle={-32} textAnchor="end" interval={0} height={76} tick={{ fontSize: 9 }} /><YAxis tick={{ fontSize: 10 }} /><Tooltip /><Bar dataKey="rate" name="Mean value" fill={COLORS[active - 1]} radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></Panel>
        <section className="cluster-members">
          <div className="cluster-members-heading"><div><span className="eyebrow">ASSIGNMENTS</span><h3>{activeDataset.id ? 'Profiles in this cluster' : 'Countries in this cluster'}</h3><p>Members assigned by {data.algorithm}.</p></div><span className="cluster-members-count">{assignment.length} {activeDataset.id ? 'profiles' : 'countries'}</span></div>
          <details className="cluster-members-details">
            <summary>{activeDataset.id ? 'View profile names' : 'View country names'}</summary>
            <div className="cluster-member-grid">{assignment.map(name => <span className="cluster-member" key={name}>{name}</span>)}</div>
          </details>
        </section>
      </div>
    </div>
  </>
}

function App() {
  return <Routes>
    <Route path="/" element={<Landing />} />
    <Route element={<Shell />}>
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/explorer" element={<ExplorerRedirect />} />
      <Route path="/clustering" element={<Clustering />} />
      <Route path="/pca" element={<PCAView />} />
      <Route path="/comparison" element={<CountryComparison />} />
      <Route path="/evaluation" element={<Evaluation />} />
      <Route path="/insights" element={<Insights />} />
      <Route path="/upload" element={<UploadDataset />} />
      <Route path="*" element={<Dashboard />} />
    </Route>
  </Routes>
}

export default App
