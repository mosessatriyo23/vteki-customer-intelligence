import { useEffect, useMemo, useState } from 'react'
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Command,
  ClipboardCheck,
  Download,
  Filter,
  Gift,
  GitBranch,
  LayoutDashboard,
  MoreHorizontal,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  UsersRound,
  WalletCards,
  X,
  AlertTriangle,
  FileSearch,
  UserCheck,
  Sliders,
  RotateCcw,
  LogOut,
} from 'lucide-react'
import { api, ApiError, getStoredToken, storeToken } from './api'
import type { ApiCampaign, ApiCustomer, ApiDecision, ApiReview, ApiUser } from './api'

type Page = 'dashboard' | 'customers' | 'campaigns' | 'reviews' | 'decisions' | 'monitoring'

type Customer = {
  apiId: number
  id: string
  name: string
  initials: string
  city: string
  tier: 'Platinum' | 'Gold' | 'Silver'
  value: string
  lastSeen: string
  email: string
  phone: string
  since: string
  visits: number | string
  nextBest: string
  color: string
}

type Campaign = {
  apiId: number
  name: string
  segment: string
  channel: string
  status: 'Live' | 'Draft' | 'Scheduled' | 'Pending approval' | 'Approved' | 'Rejected' | 'Completed'
  reach: string
  color: string
  messageDraft?: string
}

type IdentityReview = {
  apiId: number
  id: string
  subject: string
  candidates: string[]
  confidence: number
  reason: string
  status: 'Pending' | 'Approved' | 'Rejected'
}

type Decision = {
  id: string
  apiId: number
  customer: string
  recommendation: string
  rationale: string
  status: 'Proposed' | 'Overridden'
  selected?: string
  reason?: string
}

const customers: Customer[] = []
const initialCampaigns: Campaign[] = []
const initialReviews: IdentityReview[] = []
const initialDecisions: Decision[] = []

function mapCustomer(row: ApiCustomer): Customer {
  const tier = row.churn_risk === 'High' ? 'Silver' : row.ltv >= 10000 ? 'Platinum' : 'Gold'
  const colors = { Platinum: 'coral', Gold: 'teal', Silver: 'yellow' } as const
  return {
    apiId: row.id,
    id: row.customer_code,
    name: row.full_name,
    initials: row.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase(),
    city: row.segment,
    tier,
    value: new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(row.ltv),
    lastSeen: new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(new Date(row.created_at)),
    email: row.email,
    phone: '—',
    since: new Intl.DateTimeFormat('id-ID', { month: 'short', year: 'numeric' }).format(new Date(row.created_at)),
    visits: '—',
    nextBest: row.next_best_action ?? 'Belum ada rekomendasi',
    color: colors[tier],
  }
}

function mapCampaign(row: ApiCampaign): Campaign {
  const statusMap: Record<string, Campaign['status']> = {
    Active: 'Live', Draft: 'Draft', PendingApproval: 'Pending approval', Approved: 'Approved', Rejected: 'Rejected', Completed: 'Completed',
  }
  return {
    apiId: row.id,
    name: row.name,
    segment: row.target_segment,
    channel: `${row.channel} (Simulator)`,
    status: statusMap[row.status] ?? 'Draft',
    reach: '—',
    color: ['coral', 'teal', 'blue', 'yellow'][row.id % 4],
    messageDraft: row.message_draft ?? '',
  }
}

function mapReview(row: ApiReview): IdentityReview {
  return {
    apiId: row.id,
    id: `IR-${row.id}`,
    subject: row.subject_reference,
    candidates: row.candidate_references,
    confidence: row.confidence,
    reason: row.flagged_reason || row.review_note || `Kasus identitas ${row.status}; perlu keputusan reviewer.`,
    status: row.status === 'pending' ? 'Pending' : row.decision === 'approved' ? 'Approved' : 'Rejected',
  }
}

function mapDecision(row: ApiDecision): Decision {
  return {
    apiId: row.id,
    id: `NBA-${row.id}`,
    customer: `${row.customer_name} · ${row.customer_code}`,
    recommendation: row.recommended_action,
    rationale: Object.entries(row.rationale).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') || 'Rationale belum tersedia',
    status: row.status === 'overridden' ? 'Overridden' : 'Proposed',
    selected: row.selected_action ?? undefined,
    reason: row.override_reason ?? undefined,
  }
}

function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [token, setToken] = useState<string | null>(() => getStoredToken())
  const [user, setUser] = useState<ApiUser | null>(null)
  const [authLoading, setAuthLoading] = useState(() => Boolean(getStoredToken()))
  const [dataLoading, setDataLoading] = useState(false)
  const [apiError, setApiError] = useState('')
  const [customerRows, setCustomerRows] = useState<Customer[]>(customers)
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)
  const [search, setSearch] = useState('')
  const [campaigns, setCampaigns] = useState(initialCampaigns)
  const [reviews, setReviews] = useState(initialReviews)
  const [decisions, setDecisions] = useState(initialDecisions)
  const [monitoringData, setMonitoringData] = useState<{ drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }>({ drift: [], campaign_measurements: [], audit: [], pipeline_runs: [] })
  const [builderOpen, setBuilderOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [provenance, setProvenance] = useState<Record<string, unknown> | null>(null)

  async function refreshWorkspace(sessionToken: string) {
    const [customerData, campaignData, reviewData, decisionData, monitoring] = await Promise.all([
      api.customers(sessionToken),
      api.campaigns(sessionToken),
      api.reviews(sessionToken),
      api.decisions(sessionToken),
      api.monitoring(sessionToken),
    ])
    const mappedCustomers = customerData.map(mapCustomer)
    setCustomerRows(mappedCustomers)
    const activeCustomer = mappedCustomers.find((customer) => customer.apiId === selectedCustomer?.apiId) ?? mappedCustomers[0] ?? null
    setSelectedCustomer(activeCustomer)
    setProvenance(activeCustomer ? await api.customerProvenance(sessionToken, activeCustomer.apiId) : null)
    setCampaigns(campaignData.map(mapCampaign))
    setReviews(reviewData.map(mapReview))
    setDecisions(decisionData.map(mapDecision))
    setMonitoringData(monitoring)
  }

  useEffect(() => {
    if (!token) {
      setAuthLoading(false)
      return
    }
    let mounted = true
    setAuthLoading(true)
    setApiError('')
    void (async () => {
      try {
        const currentUser = await api.me(token)
        if (!mounted) return
        setUser(currentUser)
        setDataLoading(true)
        await refreshWorkspace(token)
      } catch (error) {
        if (!mounted) return
        if (error instanceof ApiError && error.status === 401) {
          storeToken(null)
          setToken(null)
          setUser(null)
        } else {
          setApiError(error instanceof Error ? error.message : 'Gagal memuat data platform.')
        }
      } finally {
        if (mounted) {
          setAuthLoading(false)
          setDataLoading(false)
        }
      }
    })()
    return () => { mounted = false }
  }, [token])

  const filteredCustomers = useMemo(
    () => customerRows.filter((customer) => `${customer.name} ${customer.city} ${customer.id}`.toLowerCase().includes(search.toLowerCase())),
    [customerRows, search],
  )

  async function handleLogin(email: string, password: string) {
    const result = await api.login(email, password)
    storeToken(result.access_token)
    setToken(result.access_token)
  }

  function logout() {
    storeToken(null)
    setToken(null)
    setUser(null)
    setCustomerRows([])
    setCampaigns([])
    setReviews([])
    setDecisions([])
    setSelectedCustomer(null)
  }

  async function saveCampaign(name: string, segment: string, channel: string, messageDraft: string) {
    if (!token) return
    try {
      const simulatorChannel = `${channel.toLowerCase().replace(/[^a-z]+/g, '_').replace(/^_|_$/g, '')}_sim`
      await api.createCampaign(token, { name, target_segment: segment, channel: simulatorChannel, message_draft: messageDraft })
      await refreshWorkspace(token)
      setBuilderOpen(false)
      setPage('campaigns')
      setNotice(`Kampanye "${name}" tersimpan di server sebagai draf.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat kampanye.')
    }
  }

  async function transitionCampaign(name: string, status: Campaign['status']) {
    if (!token) return
    const campaign = campaigns.find((item) => item.name === name)
    if (!campaign) return
    try {
      if (campaign.status === 'Draft' && status === 'Pending approval') await api.submitCampaign(token, campaign.apiId)
      else if (campaign.status === 'Pending approval' && status === 'Approved') await api.approveCampaign(token, campaign.apiId)
      else if (campaign.status === 'Pending approval' && status === 'Rejected') await api.rejectCampaign(token, campaign.apiId, 'Ditolak melalui review workflow')
      else if (campaign.status === 'Approved' && status === 'Live') await api.launchCampaign(token, campaign.apiId)
      await refreshWorkspace(token)
      setNotice(`Status kampanye "${name}" diperbarui menjadi ${status}.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal memperbarui status kampanye.')
    }
  }

  async function selectCustomer(customer: Customer) {
    setSelectedCustomer(customer)
    setProvenance(null)
    if (!token) return
    try {
      setProvenance(await api.customerProvenance(token, customer.apiId))
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal memuat provenance.')
    }
  }

  async function seedCustomers() {
    if (!token) return
    try {
      const result = await api.seedCustomers(token)
      await refreshWorkspace(token)
      setNotice(result.message)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal memuat data contoh.')
    }
  }

  async function resolveIdentityReview(id: string, approved: boolean) {
    if (!token) return
    const review = reviews.find((item) => item.id === id)
    if (!review) return
    try {
      await api.resolveReview(token, review.apiId, approved, 'Keputusan reviewer pada antrean manual')
      await refreshWorkspace(token)
      setNotice(`Identitas ${id} ${approved ? 'disetujui' : 'ditolak'}.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal menyimpan keputusan review.')
    }
  }

  async function applyHumanOverride(id: string, selected: string, reason: string) {
    if (!token) return
    const decision = decisions.find((item) => item.id === id)
    if (!decision) return
    try {
      await api.overrideDecision(token, decision.apiId, selected, reason)
      await refreshWorkspace(token)
      setNotice(`Human override ${id} tersimpan dan tercatat di audit.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal menyimpan human override.')
    }
  }

  async function createIdentityReview(subject: string, candidates: string[], confidence: number, reason: string) {
    if (!token) return
    try {
      await api.createReview(token, { subject_reference: subject, candidate_references: candidates, confidence, reason })
      await refreshWorkspace(token)
      setNotice('Kasus identity review tersimpan di antrean.')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat kasus identity review.')
    }
  }

  async function createNBARecommendation(customerId: number, action: string, rationale: Record<string, unknown>) {
    if (!token) return
    try {
      await api.createDecision(token, { customer_id: customerId, recommended_action: action, rationale })
      await refreshWorkspace(token)
      setNotice('Rekomendasi NBA tersimpan dan dapat ditinjau.')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat rekomendasi NBA.')
    }
  }

  if (authLoading) return <LoadingScreen />
  if (!token || !user) return <LoginScreen onLogin={handleLogin} error={apiError} />
  const canManageCampaigns = user.roles.some((role) => ['admin', 'campaign_manager'].includes(role))
  const canReviewIdentity = user.roles.some((role) => ['admin', 'operator'].includes(role))
  const canCreateNBA = user.roles.some((role) => ['admin', 'analyst'].includes(role))
  const canOverrideNBA = user.roles.some((role) => ['admin', 'campaign_manager'].includes(role))
  const canTrace = user.roles.some((role) => ['admin', 'analyst'].includes(role))

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <span className="brand-mark"><span /><span /><span /></span>
          <span>vteki<span className="brand-dot">.</span></span>
        </div>
        
        <div className="workspace-switch">
          <span className="workspace-icon">N</span>
          <span className="workspace-copy">
            <b>Nusa Beauty Group</b>
            <small>Customer Intelligence</small>
          </span>
          <ChevronDown size={15} />
        </div>

        <div className="persona-box">
          <div className="persona-label">ROLE AKTIF DARI SERVER</div>
          <div className="role-list">{user.roles.map((role) => <span className="role-chip" key={role}>{role}</span>)}</div>
        </div>

        <div className="nav-label">NAVIGASI UTAMA</div>
        <nav className="main-nav" aria-label="Main navigation">
          <NavItem active={page === 'dashboard'} icon={<LayoutDashboard size={18} />} label="Overview" onClick={() => setPage('dashboard')} />
          <NavItem active={page === 'customers'} icon={<UsersRound size={18} />} label="Customer 360" onClick={() => setPage('customers')} count={customerRows.length ? `${customerRows.length}` : undefined} />
          <NavItem active={page === 'campaigns'} icon={<Send size={18} />} label="Campaigns & Approval" onClick={() => setPage('campaigns')} count={campaigns.filter(c => c.status === 'Pending approval').length ? `${campaigns.filter(c => c.status === 'Pending approval').length}` : undefined} />
          <NavItem active={page === 'reviews'} icon={<ClipboardCheck size={18} />} label="Manual Review Identitas" onClick={() => setPage('reviews')} count={reviews.filter(r => r.status === 'Pending').length ? `${reviews.filter(r => r.status === 'Pending').length}` : undefined} />
          <NavItem active={page === 'decisions'} icon={<Sparkles size={18} />} label="Next-Best-Action & Override" onClick={() => setPage('decisions')} />
          <NavItem active={page === 'monitoring'} icon={<ChartNoAxesCombined size={18} />} label="Monitoring & Audit Trace" onClick={() => setPage('monitoring')} />
        </nav>

        <div className="nav-label tools-label">GOVERNANCE & NFR</div>
        <nav className="main-nav" aria-label="Governance">
          <NavItem active={false} icon={<WalletCards size={18} />} label="PostgreSQL Schemas (8)" onClick={() => setNotice('PostgreSQL Schemas: core, stg, feat, ml, dec, act, msr, gov')} />
          <NavItem active={false} icon={<ShieldCheck size={18} />} label="RBAC & Audit Service" onClick={() => setNotice('JWT Auth + bcrypt + append-only audit_event (correlation_id)')} />
        </nav>

        <div className="sidebar-spacer" />
        <div className="sidebar-bottom">
          <button className="plain-nav" onClick={() => setNotice('CI/CD Pipeline: GitHub Actions + mypy + Schemathesis + T-SEC-03 Allowlist')}><CircleHelp size={17} /> CI/CD & Security</button>
          <button className="plain-nav" onClick={logout}><LogOut size={17} /> Keluar</button>
          <div className="profile-row">
            <div className="avatar avatar-dark">PA</div>
            <div className="profile-copy">
              <b>{user.email}</b>
              <small>{user.roles.join(', ')}</small>
            </div>
            <MoreHorizontal size={17} />
          </div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Platform Architect</span>
            <span className="crumb-slash">/</span>
            <b>{pageTitle(page)}</b>
          </div>
          <div className="top-actions">
            <button className="global-search" onClick={() => setPage('customers')}>
              <Search size={16} />
              <span>Search customer, audit, campaign</span>
              <kbd><Command size={11} /> K</kbd>
            </button>
            <button className="icon-button notification-button" aria-label="Notifications" onClick={() => setNotice('Sistem Audit & Pipeline 60-min berjalan normal')}>
              <Bell size={18} />
              <i />
            </button>
            <div className="avatar avatar-coral">{user.email.slice(0, 2).toUpperCase()}</div>
          </div>
        </header>

        {apiError && <div className="api-alert" role="alert"><span>{apiError}</span><button onClick={() => setApiError('')} aria-label="Tutup pesan"><X size={15} /></button></div>}
        {dataLoading && <div className="sync-note">Sinkronisasi data dari API…</div>}

        <main className="page-content" key={page}>
          {page === 'dashboard' && (
            <Dashboard 
              campaigns={campaigns} 
              customers={customerRows}
              reviews={reviews}
              decisions={decisions}
              monitoring={monitoringData}
              onSeedCustomers={seedCustomers}
              canSeed={user.roles.includes('admin')}
              canManageCampaigns={canManageCampaigns}
              onOpenCustomers={() => setPage('customers')} 
              onNewCampaign={() => setBuilderOpen(true)} 
              onNavigate={(p) => setPage(p)}
            />
          )}
          {page === 'customers' && <CustomerPage customers={filteredCustomers} selected={selectedCustomer} provenance={provenance} onSelect={selectCustomer} search={search} onSearch={setSearch} onSeed={seedCustomers} canSeed={user.roles.includes('admin')} />}
          {page === 'campaigns' && <CampaignPage campaigns={campaigns} canManage={canManageCampaigns} onNew={() => setBuilderOpen(true)} onTransition={transitionCampaign} />}
          {page === 'reviews' && (
            <IdentityReviewPage 
              reviews={reviews} 
              onResolve={resolveIdentityReview}
              onCreate={createIdentityReview}
              canResolve={canReviewIdentity}
            />
          )}
          {page === 'decisions' && (
            <DecisionPage 
              decisions={decisions} 
              onOverride={applyHumanOverride}
              customers={customerRows}
              onCreate={createNBARecommendation}
              canCreate={canCreateNBA}
              canOverride={canOverrideNBA}
            />
          )}
          {page === 'monitoring' && <MonitoringPage token={token} data={monitoringData} canTrace={canTrace} />}
        </main>
      </div>

      {builderOpen && <CampaignBuilder customers={customerRows} onClose={() => setBuilderOpen(false)} onSave={saveCampaign} />}
      {notice && (
        <div className="toast" role="status">
          <Check size={16} />
          {notice}
          <button aria-label="Dismiss" onClick={() => setNotice('')}><X size={15} /></button>
        </div>
      )}
    </div>
  )
}

function pageTitle(page: Page) {
  return {
    dashboard: 'Overview Governance & Operations',
    customers: 'Customer 360 & Data Provenance',
    campaigns: 'Campaign Studio & Approval Workflow',
    reviews: 'Antrean Manual Review Identitas',
    decisions: 'Layar Eksekusi NBA & Human Override',
    monitoring: 'Dashboard Monitoring, Drift & Audit Trace',
  }[page]
}

function NavItem({ active, icon, label, count, onClick }: { active: boolean; icon: React.ReactNode; label: string; count?: string; onClick: () => void }) {
  return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>{icon}<span>{label}</span>{count && <small>{count}</small>}</button>
}

function PageHeading({ eyebrow, title, subtitle, action }: { eyebrow: string; title: string; subtitle: string; action?: React.ReactNode }) {
  return <div className="page-heading"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="heading-action">{action}</div>}</div>
}

function Dashboard({ campaigns, customers: customerRows, reviews, decisions, monitoring, onSeedCustomers, canSeed, canManageCampaigns, onOpenCustomers, onNewCampaign, onNavigate }: { campaigns: Campaign[]; customers: Customer[]; reviews: IdentityReview[]; decisions: Decision[]; monitoring: { drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }; onSeedCustomers: () => void; canSeed: boolean; canManageCampaigns: boolean; onOpenCustomers: () => void; onNewCampaign: () => void; onNavigate: (p: Page) => void }) {
  const measurements = monitoring.campaign_measurements
  const driftMetrics = monitoring.drift
  const pipelineRun = monitoring.pipeline_runs[0]
  const observedTotal = measurements.reduce((sum, item) => sum + Number(item.observed ?? 0), 0)
  const incrementalTotal = measurements.reduce((sum, item) => sum + Number(item.incremental ?? 0), 0)
  const driftValue = driftMetrics.length ? Math.max(...driftMetrics.map((item) => Number(item.value ?? 0))) : null
  const pipelineLabel = pipelineRun ? String(pipelineRun.status) : 'Belum ada run'
  return <>
    <PageHeading 
      eyebrow="CAPSTONE INTELLIGENCE PLATFORM" 
      title="Architecture & Governance Dashboard" 
      subtitle="Monitoring skema PostgreSQL terpartisi (core, stg, feat, ml, dec, act, msr, gov), pipeline APScheduler (NFR-01), dan alur persetujuan." 
      action={
        <>
          <button className="button button-secondary" onClick={() => onNavigate('monitoring')}><FileSearch size={15} /> Audit Trace (SLA &le; 5m)</button>
          {canManageCampaigns && <button className="button button-primary" onClick={onNewCampaign}><Plus size={16} /> Buat Kampanye</button>}
        </>
      } 
    />

    <section className="metric-grid" aria-label="Key metrics">
      <Metric label="Total Pelanggan 360" value={customerRows.length.toLocaleString('id-ID')} change="API" detail="core.customers" icon={<UsersRound size={16} />} positive />
      <Metric label="Antrean Review Identitas" value={`${reviews.filter(r => r.status === 'Pending').length}`} change="Saat ini" detail="manual review pending" icon={<UserCheck size={16} />} positive={false} />
      <Metric label="Keputusan NBA" value={`${decisions.length}`} change="Persisten" detail="dec.nba_decisions" icon={<Sparkles size={16} />} positive />
      <Metric label="Pipeline NFR-01" value={pipelineLabel} change={pipelineRun ? 'Scheduler' : 'Menunggu'} detail="advisory run lock · budget 60m" icon={<Clock3 size={16} />} positive={pipelineRun?.status === 'completed'} />
    </section>

    <section className="insight-grid">
      <article className="panel revenue-panel">
        <div className="panel-heading"><div><div className="panel-kicker">ANALISIS HASIL TERAMATI VS INKREMENTAL</div><h2>Hasil Teramati vs Inkremen Lift (A/B Test)</h2></div><button className="more-button" aria-label="More options"><MoreHorizontal size={20} /></button></div>
        {measurements.length ? <>
          <div className="revenue-total"><strong>{observedTotal.toLocaleString('id-ID')} observed</strong><span className="delta">{incrementalTotal.toLocaleString('id-ID')} incremental</span><small>Jumlah record hasil pengukuran dari msr.campaign_measurements</small></div>
          <div className="measurement-list">{measurements.slice(0, 6).map((item, index) => <div className="measurement-row" key={`${item.campaign_id}-${index}`}><span>{String(item.metric ?? `Campaign ${item.campaign_id}`)}</span><div className="measurement-bars"><i style={{ width: `${Math.min(100, Math.max(2, Number(item.observed ?? 0)))}%` }} /><b style={{ width: `${Math.min(100, Math.max(2, Number(item.incremental ?? 0)))}%` }} /></div><small>{Number(item.observed ?? 0)} / {Number(item.incremental ?? 0)}</small></div>)}</div>
        </> : <div className="empty-state">Belum ada hasil observed-vs-incremental yang tercatat di API.</div>}
      </article>

      <article className="panel segment-panel">
        <div className="panel-heading"><div><div className="panel-kicker">MONITORING PERGESERAN MODEL</div><h2>Model Drift (PSI Status)</h2></div><button className="more-button" aria-label="More segment options"><MoreHorizontal size={20} /></button></div>
        {driftValue !== null ? <><div className="segment-total"><strong>PSI {driftValue.toFixed(2)}</strong><span>{driftMetrics.length} measured models</span></div><div className="segment-stack"><span className="segment-platinum" /><span className="segment-gold" /><span className="segment-silver" /><span className="segment-risk" /></div><div className="segment-legend">{driftMetrics.slice(0, 4).map((item, index) => <SegmentRow key={`${item.model}-${index}`} label={String(item.model ?? 'model')} count={`PSI ${Number(item.value ?? 0).toFixed(2)}`} percent={String(item.status ?? '')} tone={index % 2 ? 'gold' : 'platinum'} />)}</div></> : <div className="empty-state">Belum ada metrik drift model di API.</div>}
        <button className="text-link" onClick={() => onNavigate('monitoring')}>Lihat detail Monitoring & Audit Log <ArrowRight size={15} /></button>
      </article>
    </section>

    <section className="bottom-grid">
      <article className="panel table-panel">
        <div className="panel-heading panel-heading-table"><div><div className="panel-kicker">ANTREAN IDENTITAS</div><h2>Identity Review Pending</h2></div><button className="button button-quiet" onClick={() => onNavigate('reviews')}>Lihat Semua <ArrowRight size={14} /></button></div>
        <div className="mini-review-list">
          {reviews.filter((review) => review.status === 'Pending').map(r => (
            <div className="mini-review-item" key={r.id}>
              <div>
                <b>{r.id}: {r.subject}</b>
                <small>{r.reason}</small>
              </div>
              <span className={`status-badge status-${r.status.toLowerCase()}`}>{r.status}</span>
            </div>
          ))}
          {!reviews.some((review) => review.status === 'Pending') && <div className="empty-state">Tidak ada review identitas yang menunggu.</div>}
        </div>
      </article>

      <article className="panel campaign-mini-panel">
        <div className="panel-heading panel-heading-table"><div><div className="panel-kicker">HUMAN APPROVAL WORKFLOW</div><h2>Draf Kampanye Menunggu Persetujuan</h2></div><button className="more-button" aria-label="Options"><MoreHorizontal size={20} /></button></div>
        <div className="mini-campaign-list">{campaigns.filter((campaign) => ['Draft', 'Pending approval', 'Approved'].includes(campaign.status)).slice(0, 3).map((campaign) => <div className="mini-campaign" key={campaign.apiId}><div className={`campaign-symbol ${campaign.color}`}><Gift size={16} /></div><div className="mini-campaign-copy"><b>{campaign.name}</b><small>{campaign.segment}</small></div><StatusBadge status={campaign.status} /></div>)}{!campaigns.some((campaign) => ['Draft', 'Pending approval', 'Approved'].includes(campaign.status)) && <div className="empty-state">Belum ada campaign yang menunggu workflow.</div>}</div>
        <button className="text-link" onClick={() => onNavigate('campaigns')}>Buka Studio Kampanye <ArrowRight size={15} /></button>
      </article>
    </section>

    <article className="panel table-panel dashboard-customer-panel">
      <div className="panel-heading panel-heading-table">
        <div><div className="panel-kicker">CUSTOMER 360</div><h2>Pelanggan terakhir aktif</h2></div>
        <button className="button button-quiet" onClick={onOpenCustomers}>Buka Customer 360 <ArrowRight size={14} /></button>
      </div>
      {customerRows.length ? <CustomerTable rows={customerRows.slice(0, 3)} compact /> : <div className="empty-state">Belum ada customer di core.customers.{canSeed && <button className="button button-secondary" onClick={onSeedCustomers}>Muat data contoh</button>}</div>}
    </article>

    <div className="data-note">
      <ShieldCheck size={14} /> Keamanan & Compliance T-SEC-03: Channel Simulator aktif (Tanpa vendor email/SMS eksternal) <span>Append-only Audit Log Active</span>
    </div>
  </>
}

function Metric({ label, value, change, detail, icon, positive }: { label: string; value: string; change: string; detail: string; icon: React.ReactNode; positive: boolean }) {
  return <article className="metric"><div className="metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><div className={`metric-foot ${positive ? 'is-positive' : 'is-negative'}`}>{positive ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}<b>{change}</b><span>{detail}</span></div></article>
}

function SegmentRow({ label, count, percent, tone }: { label: string; count: string; percent: string; tone: string }) {
  return <div className="segment-row"><span className={`legend-dot ${tone}`} /><span className="segment-name">{label}</span><b>{count}</b><small>{percent}</small></div>
}

function CustomerPage({ customers: rows, selected, provenance, onSelect, search, onSearch, onSeed, canSeed }: { customers: Customer[]; selected: Customer | null; provenance: Record<string, unknown> | null; onSelect: (customer: Customer) => void; search: string; onSearch: (value: string) => void; onSeed: () => void; canSeed: boolean }) {
  return <>
    <PageHeading eyebrow="CUSTOMER DATA PLATFORM" title="Customer 360 & Provenance" subtitle="Tampilan menyeluruh pelanggan dengan riwayat data provenance dan consent." action={<><button className="button button-secondary"><Filter size={15} /> Filter Segment</button><button className="button button-primary"><Download size={15} /> Ekspor Data</button></>} />
    <div className="customer-layout">
      <section className="panel customer-list-panel">
        <div className="list-toolbar"><div className="inline-search"><Search size={16} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Cari pelanggan berdasarkan kode/nama" aria-label="Search customers" /></div><button className="icon-button filter-icon" aria-label="Filter customers"><Filter size={16} /></button></div>
        <div className="customer-count"><b>Semua Pelanggan</b><span>{rows.length}</span><ChevronDown size={14} /></div>
        <CustomerTable rows={rows} onSelect={onSelect} selectedId={selected?.id} />
        {rows.length === 0 && <div className="empty-state">{search ? `Tidak ada pelanggan dengan kata kunci “${search}”.` : 'Belum ada customer di API.'}{!search && canSeed && <button className="button button-secondary" onClick={onSeed}>Muat data contoh</button>}</div>}
        <div className="list-footer">Menampilkan {rows.length} pelanggan dari API <button onClick={onSeed} disabled={!canSeed || rows.length > 0}>Muat data contoh</button></div>
      </section>
      {selected && <CustomerProfile customer={selected} provenance={provenance} />}
    </div>
  </>
}

function CustomerTable({ rows, compact = false, onSelect, selectedId }: { rows: Customer[]; compact?: boolean; onSelect?: (customer: Customer) => void; selectedId?: string }) {
  return <div className={`customer-table-wrap ${compact ? 'compact-table' : ''}`}><table className="customer-table"><thead><tr><th>Pelanggan</th><th>Value band</th><th>Lifetime Value</th><th>Tercatat</th></tr></thead><tbody>{rows.map((customer) => <tr key={customer.id} className={selectedId === customer.id ? 'selected-row' : ''} onClick={() => onSelect?.(customer)}><td><div className="table-customer"><div className={`avatar avatar-${customer.color}`}>{customer.initials}</div><div><b>{customer.name}</b><small>{customer.city} · {customer.id}</small></div></div></td><td><TierBadge tier={customer.tier} /></td><td className="value-cell">{customer.value}</td><td className="last-active">{customer.lastSeen}</td></tr>)}</tbody></table></div>
}

function CustomerProfile({ customer, provenance }: { customer: Customer; provenance: Record<string, unknown> | null }) {
  const features = (provenance?.features as Array<Record<string, unknown>> | undefined) ?? []
  const audit = (provenance?.audit as Array<Record<string, unknown>> | undefined) ?? []
  const traces = (provenance?.decision_traces as Array<Record<string, unknown>> | undefined) ?? []
  return <aside className="panel profile-panel">
    <div className="profile-cover"><span className="cover-orbit cover-orbit-one" /><span className="cover-orbit cover-orbit-two" /><button className="more-button cover-more" aria-label="More customer options"><MoreHorizontal size={20} /></button><div className={`profile-avatar avatar-${customer.color}`}>{customer.initials}</div></div>
    <div className="profile-main">
      <div className="profile-name-row"><div><h2>{customer.name}</h2><span>{customer.id}</span></div><TierBadge tier={customer.tier} /></div>
      <p className="profile-location">Segmen {customer.city} <span>·</span> Tercatat sejak {customer.since}</p>
      <div className="profile-actions"><button className="button button-secondary" disabled title="Tidak ada pengiriman pesan eksternal pada platform ini"><ShieldCheck size={14} /> Channel simulator only</button><button className="button button-secondary" aria-label="Opsi profil"><MoreHorizontal size={17} /></button></div>
      <div className="profile-stats"><div><small>Lifetime Value</small><b>{customer.value}</b></div><div><small>Total Kunjungan</small><b>{customer.visits}</b></div></div>
      <div className="profile-section"><div className="profile-section-title">KONTAK VERIFIKASI <button aria-label="Edit contact details"><MoreHorizontal size={16} /></button></div><div className="contact-line"><span className="contact-icon">@</span>{customer.email}</div><div className="contact-line"><span className="contact-icon">#</span>{customer.phone}</div></div>
      <div className="profile-section"><div className="profile-section-title">NEXT-BEST-ACTION (AI) <Sparkles size={15} /></div><div className="next-action"><div className="next-action-icon"><Gift size={17} /></div><div><b>{customer.nextBest}</b><small>Affinities Tinggi · 78% Likelihood</small></div><ArrowRight size={15} /></div></div>
      
      <div className="profile-section">
        <div className="profile-section-title">RIWAYAT PROVENANCE DATA <GitBranch size={14} /></div>
        <div className="provenance-timeline">
          <div className="prov-item">
            <span className="prov-dot core-dot" />
            <div>
              <b>{String(provenance?.source ?? 'core.customers')}</b>
              <small>Master record dari API</small>
              <time>{customer.id}</time>
            </div>
          </div>
          {features.map((feature, index) => <div className="prov-item" key={`feature-${index}`}>
            <span className="prov-dot feat-dot" />
            <div>
              <b>feat.customer_features · {String(feature.feature)}</b>
              <small>{JSON.stringify(feature.value)}</small>
              <time>{String(feature.computed_at ?? '')}</time>
            </div>
          </div>)}
          {traces.map((trace, index) => <div className="prov-item" key={`trace-${index}`}>
            <span className="prov-dot dec-dot" />
            <div>
              <b>dec.nba_decisions · {String(trace.trigger_event)}</b>
              <small>{String(trace.decision_output)}</small>
              <time>Correlation ID {String(trace.correlation_id)}</time>
            </div>
          </div>)}
          {audit.map((event, index) => <div className="prov-item" key={`audit-${index}`}>
            <span className="prov-dot feat-dot" />
            <div><b>{String(event.event_type)}</b><small>{JSON.stringify(event.details)}</small><time>Correlation ID {String(event.correlation_id)}</time></div>
          </div>)}
          {!features.length && !traces.length && !audit.length && <small className="provenance-empty">Belum ada feature, decision, atau audit event yang terkait.</small>}
        </div>
      </div>

      <div className="consent-footer"><ShieldCheck size={15} /><span>Consent detail belum diekspos oleh Customer API</span><button aria-label="Consent details"><ArrowRight size={14} /></button></div>
    </div>
  </aside>
}

function CampaignPage({ campaigns, canManage, onNew, onTransition }: { campaigns: Campaign[]; canManage: boolean; onNew: () => void; onTransition: (name: string, status: Campaign['status']) => void }) {
  const [activeFilter, setActiveFilter] = useState('All campaigns')
  const visible = campaigns.filter((campaign) => activeFilter === 'All campaigns' || campaign.status === activeFilter)
  const liveCount = campaigns.filter((campaign) => campaign.status === 'Live').length
  const pendingCount = campaigns.filter((campaign) => campaign.status === 'Pending approval').length

  return <>
    <PageHeading eyebrow="ENGAGEMENT & APPROVAL WORKFLOW" title="Campaign Studio & Persetujuan Draf" subtitle="Formulir pembuatan kampanye, peninjauan draf pesan, dan alur persetujuan (Human Approval Workflow)." action={canManage && <button className="button button-primary" onClick={onNew}><Plus size={16} /> Kampanye Baru</button>} />
    <section className="campaign-summary">
      <div><span>Total campaign</span><b>{campaigns.length}</b><small>Data tersimpan pada act.campaigns</small></div>
      <div><span>Live / berjalan</span><b>{liveCount}</b><small>Dari respons API</small></div>
      <div><span>Menunggu approval</span><b>{pendingCount}</b><small><ShieldCheck size={14} /> Channel simulator only</small></div>
      <div className="summary-illustration"><span className="summary-ring ring-one" /><span className="summary-ring ring-two" /><span className="summary-star"><Sparkles size={21} /></span></div>
    </section>

    <div className="campaign-toolbar">
      <div className="filter-tabs">
        {['All campaigns', 'Live', 'Pending approval', 'Draft', 'Approved'].map((filter) => (
          <button className={activeFilter === filter ? 'selected' : ''} onClick={() => setActiveFilter(filter)} key={filter}>
            {filter}
            <span>{filter === 'All campaigns' ? campaigns.length : campaigns.filter((c) => c.status === filter).length}</span>
          </button>
        ))}
      </div>
      <button className="button button-secondary"><Filter size={15} /> Filter</button>
    </div>

    <section className="panel campaign-table-panel">
      <table className="campaign-table">
        <thead>
          <tr>
            <th>Kampanye & Draf Pesan</th>
            <th>Segmen Audiens</th>
            <th>Channel</th>
            <th>Estimasi Jangkauan</th>
            <th>Status Workflow</th>
            <th>Aksi Persetujuan</th>
          </tr>
        </thead>
        <tbody>
          {visible.map((campaign, index) => (
            <tr key={`${campaign.name}-${index}`}>
              <td>
                <div className="campaign-cell">
                  <div className={`campaign-symbol ${campaign.color}`}><Gift size={17} /></div>
                  <div>
                    <b>{campaign.name}</b>
                    <small className="draft-preview-text">{campaign.messageDraft || 'Draf pesan kampanye belum diisi'}</small>
                  </div>
                </div>
              </td>
              <td>{campaign.segment}</td>
              <td><span className="channel-pill">{campaign.channel}</span></td>
              <td>{campaign.reach}</td>
              <td><StatusBadge status={campaign.status} /></td>
              <td>
                <div className="action-button-group">
                  {!canManage ? <span className="text-muted-sm">Read only</span> : campaign.status === 'Draft' ? (
                    <button className="button-sm button-approve" onClick={() => onTransition(campaign.name, 'Pending approval')}>
                      <FileSearch size={13} /> Ajukan Approval
                    </button>
                  ) : campaign.status === 'Pending approval' ? (
                    <>
                      <button className="button-sm button-approve" onClick={() => onTransition(campaign.name, 'Approved')}>
                        <Check size={13} /> Setujui
                      </button>
                      <button className="button-sm button-reject" onClick={() => onTransition(campaign.name, 'Rejected')}>
                        <X size={13} /> Tolak
                      </button>
                    </>
                  ) : campaign.status === 'Approved' ? (
                    <button className="button-sm button-launch" onClick={() => onTransition(campaign.name, 'Live')}>
                      <Send size={13} /> Peluncuran Sim
                    </button>
                  ) : (
                    <span className="text-muted-sm">Selesai</span>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <div className="empty-state">Tidak ada kampanye pada kategori ini.</div>}
      <div className="list-footer">Menampilkan {visible.length} dari {campaigns.length} kampanye <button>Muat Lebih Banyak</button></div>
    </section>
  </>
}

function IdentityReviewPage({ reviews, onResolve, onCreate, canResolve }: { reviews: IdentityReview[]; onResolve: (id: string, approved: boolean) => void; onCreate: (subject: string, candidates: string[], confidence: number, reason: string) => void; canResolve: boolean }) {
  const [createOpen, setCreateOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [candidates, setCandidates] = useState('')
  const [confidence, setConfidence] = useState('0.7')
  const [reason, setReason] = useState('')
  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const candidateList = candidates.split(',').map((item) => item.trim()).filter(Boolean)
    if (!subject.trim() || !candidateList.length || reason.trim().length < 5) return
    onCreate(subject.trim(), candidateList, Number(confidence), reason.trim())
    setSubject('')
    setCandidates('')
    setReason('')
    setCreateOpen(false)
  }
  return <>
    <PageHeading 
      eyebrow="IDENTITY GOVERNANCE" 
      title="Antrean Manual Review Identitas" 
      subtitle="Antrean peninjauan resolusi identitas pelanggan (Identity Matching) dengan tingkat kepercayaan (confidence) sedang/rendah."
      action={canResolve && <button className="button button-primary" onClick={() => setCreateOpen((open) => !open)}><Plus size={15} /> Tambah kasus</button>}
    />
    {createOpen && <form className="panel review-create-form" onSubmit={submit}><label className="field-label">Referensi utama<input required value={subject} onChange={(event) => setSubject(event.target.value)} placeholder="CRM-883104" /></label><label className="field-label">Kandidat, pisahkan dengan koma<input required value={candidates} onChange={(event) => setCandidates(event.target.value)} placeholder="POS-440218, APP-103338" /></label><label className="field-label">Confidence (0–1)<input required type="number" min="0" max="1" step="0.01" value={confidence} onChange={(event) => setConfidence(event.target.value)} /></label><label className="field-label">Alasan flagging<input required minLength={5} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Contoh: nomor sama, kode member berbeda" /></label><button className="button button-primary" type="submit">Masukkan ke antrean</button></form>}
    <div className="review-grid">
      {reviews.map(r => (
        <article className="panel review-card" key={r.id}>
          <div className="review-card-header">
            <div>
              <span className="review-id">{r.id}</span>
              <h3>{r.subject}</h3>
            </div>
            <span className={`status-badge status-${r.status.toLowerCase()}`}>{r.status}</span>
          </div>

          <div className="review-body">
            <div className="confidence-meter">
              <div className="confidence-label">
                <span>Skor Kemiripan Identitas (Match Confidence)</span>
                <b>{Math.round(r.confidence * 100)}%</b>
              </div>
              <div className="meter-track">
                <div className="meter-fill" style={{ width: `${r.confidence * 100}%` }} />
              </div>
            </div>

            <div className="review-reason">
              <AlertTriangle size={15} />
              <p><b>Penyebab Flagging:</b> {r.reason}</p>
            </div>

            <div className="candidates-list">
              <div className="candidates-title">KANDIDAT PROFIL COCOK:</div>
              {r.candidates.map((c, i) => (
                <div className="candidate-chip" key={i}>
                  <GitBranch size={13} />
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </div>

          {r.status === 'Pending' && canResolve ? (
            <div className="review-card-footer">
              <button className="button button-secondary" onClick={() => onResolve(r.id, false)}>
                <X size={15} /> Tolak Gabung Identitas
              </button>
              <button className="button button-primary" onClick={() => onResolve(r.id, true)}>
                <Check size={15} /> Setujui Digabungkan (Merge)
              </button>
            </div>
          ) : r.status !== 'Pending' ? (
            <div className="resolved-note">
              <Check size={14} /> Resolusi Identitas Telah Diselesaikan
            </div>
          ) : (
            <div className="resolved-note">Role aktif hanya dapat melihat antrean.</div>
          )}
        </article>
      ))}
      {!reviews.length && <div className="panel empty-state">Antrean review dari API masih kosong. Tambahkan kasus untuk memulai workflow.</div>}
    </div>
  </>
}

function DecisionPage({ decisions, onOverride, customers: customerRows, onCreate, canCreate, canOverride }: { decisions: Decision[]; onOverride: (id: string, selected: string, reason: string) => void; customers: Customer[]; onCreate: (customerId: number, action: string, rationale: Record<string, unknown>) => void; canCreate: boolean; canOverride: boolean }) {
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null)
  const [customAction, setCustomAction] = useState('')
  const [reason, setReason] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newCustomerId, setNewCustomerId] = useState('')
  const [newAction, setNewAction] = useState('')

  function handleOverrideSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedDecision || !customAction.trim() || !reason.trim()) return
    onOverride(selectedDecision.id, customAction.trim(), reason.trim())
    setSelectedDecision(null)
    setCustomAction('')
    setReason('')
  }

  return <>
    <PageHeading 
      eyebrow="NEXT-BEST-ACTION & HUMAN OVERRIDE" 
      title="Layar Eksekusi NBA & Interface Human Override" 
      subtitle="Peninjauan rekomendasi Next-Best-Action dari model AI beserta fasilitas Human Override manual dengan logging justifikasi."
      action={canCreate && <button className="button button-primary" onClick={() => setCreateOpen((open) => !open)} disabled={!customerRows.length}><Plus size={15} /> Buat proposal NBA</button>}
    />
    {createOpen && <form className="panel decision-create-form" onSubmit={(event) => { event.preventDefault(); const customer = customerRows.find((item) => item.apiId === Number(newCustomerId)); if (!customer || !newAction.trim()) return; onCreate(customer.apiId, newAction.trim(), { source: 'customer_360', customer_code: customer.id, segment: customer.city }); setCreateOpen(false); setNewAction('') }}><label className="field-label">Pelanggan<select required value={newCustomerId} onChange={(event) => setNewCustomerId(event.target.value)}><option value="">Pilih customer</option>{customerRows.map((customer) => <option key={customer.apiId} value={customer.apiId}>{customer.name} · {customer.id}</option>)}</select></label><label className="field-label">Recommended action<input required value={newAction} onChange={(event) => setNewAction(event.target.value)} placeholder="Tindakan yang direkomendasikan" /></label><button className="button button-primary" type="submit">Simpan proposal</button></form>}
    <div className="decision-grid">
      {decisions.map(d => (
        <article className="panel decision-card" key={d.id}>
          <div className="decision-header">
            <div>
              <span className="nba-id">{d.id}</span>
              <h3>{d.customer}</h3>
            </div>
            <span className={`status-badge ${d.status === 'Overridden' ? 'status-scheduled' : 'status-live'}`}>{d.status}</span>
          </div>

          <div className="decision-body">
            <div className="nba-box">
              <div className="nba-label">REKOMENDASI AI MODEL:</div>
              <div className="nba-text"><Sparkles size={16} /> {d.recommendation}</div>
              <small>{d.rationale}</small>
            </div>

            {d.status === 'Overridden' && (
              <div className="override-box">
                <div className="override-label"><Sliders size={14} /> DITERAPKAN HUMAN OVERRIDE:</div>
                <b className="override-action">{d.selected}</b>
                <p><b>Alasan Override:</b> {d.reason}</p>
              </div>
            )}
          </div>

          <div className="decision-footer">
            {canOverride && d.status === 'Proposed' && <button className="button button-secondary" onClick={() => setSelectedDecision(d)}>
              <RotateCcw size={14} /> Human Override Manual
            </button>}
          </div>
        </article>
      ))}
      {!decisions.length && <div className="panel empty-state">Belum ada rekomendasi NBA tersimpan. Buat proposal dari customer yang tersedia.</div>}
    </div>

    {selectedDecision && (
      <div className="modal-backdrop">
        <div className="builder-modal override-modal">
          <div className="builder-header">
            <div>
              <h2 id="builder-title">Human Override Next-Best-Action</h2>
              <p>Formulir pengambilalihan rekomendasi AI secara manual untuk {selectedDecision.customer}</p>
            </div>
            <button className="icon-button" onClick={() => setSelectedDecision(null)}><X size={18} /></button>
          </div>
          <form onSubmit={handleOverrideSubmit}>
            <div className="builder-body-simple">
              <label className="field-label">
                Rekomendasi AI Saat Ini
                <input disabled value={selectedDecision.recommendation} />
              </label>
              <label className="field-label">
                Tindakan Override Baru (Manual Action)
                <input 
                  required 
                  placeholder="Contoh: Berikan Pendampingan VIP Roundtable Q4" 
                  value={customAction} 
                  onChange={(e) => setCustomAction(e.target.value)} 
                />
              </label>
              <label className="field-label">
                Alasan & Justifikasi Pengambilalihan (Mandatory Audit Reason)
                <textarea 
                  required 
                  rows={3} 
                  placeholder="Jelaskan alasan bisnis pengambilalihan keputusan..." 
                  value={reason} 
                  onChange={(e) => setReason(e.target.value)} 
                />
              </label>
            </div>
            <div className="builder-footer">
              <button type="button" className="button button-secondary" onClick={() => setSelectedDecision(null)}>Batal</button>
              <button type="submit" className="button button-primary">Simpan Override</button>
            </div>
          </form>
        </div>
      </div>
    )}
  </>
}

function MonitoringPage({ token, data, canTrace }: { token: string; data: { drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }; canTrace: boolean }) {
  const [traceId, setTraceId] = useState('')
  const [tracing, setTracing] = useState(false)
  const [traceResult, setTraceResult] = useState<Record<string, unknown> | null>(null)
  const [traceError, setTraceError] = useState('')

  async function runTrace(e: React.FormEvent) {
    e.preventDefault()
    if (!traceId.trim()) return
    setTracing(true)
    setTraceError('')
    try {
      setTraceResult(await api.reconstruct(token, traceId.trim()))
    } catch (error) {
      setTraceResult(null)
      setTraceError(error instanceof Error ? error.message : 'Trace tidak dapat direkonstruksi.')
    } finally {
      setTracing(false)
    }
  }

  return <>
    <PageHeading 
      eyebrow="MANAGEMENT DASHBOARD & AUDIT TRACE" 
      title="Monitoring Drift, Lift & Audit Trace" 
      subtitle="Visualisasi hasil teramati vs inkremental, monitoring pergeseran model (drift), dan penelusuran balik 'Mengapa hal ini terjadi?' (&le; 5m SLA)."
    />

    <section className="monitoring-sections">
      {/* 1. Audit Trace Search Box */}
      {canTrace && <article className="panel trace-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">PENELUSURAN BALIK AUDIT (AUDIT TRACE SLA &le; 5M)</div>
            <h2>Mengapa Hal Ini Terjadi? (Decision Reconstruction)</h2>
          </div>
        </div>
        
        <form onSubmit={runTrace} className="trace-form">
          <div className="inline-search trace-search">
            <FileSearch size={18} />
            <input 
              value={traceId} 
              onChange={(e) => setTraceId(e.target.value)} 
              placeholder="Masukkan correlation_id workflow..." 
            />
          </div>
          <button type="submit" className="button button-primary" disabled={tracing}>
            {tracing ? 'Rekonstruksi...' : 'Jalankan Penelusuran Trace'}
          </button>
        </form>
        {traceError && <p className="field-error">{traceError}</p>}

        {traceResult && (
          <div className="trace-result-box">
            <div className="trace-summary">
              <span><b>Correlation ID:</b> {String(traceResult.correlation_id)}</span>
              <span><b>Jenis:</b> {String(traceResult.decision_type)}</span>
              <span><b>Waktu Rekonstruksi:</b> <b className="text-green">{Number(traceResult.reconstructed_in_seconds).toFixed(4)} detik</b> (SLA &lt; 5 menit)</span>
            </div>
            <div className="trace-steps">
              {(traceResult.audit_events as Array<Record<string, unknown>>).map((s, index) => (
                <div className="trace-step-item" key={index}>
                  <div className="step-time">{String(s.occurred_at)}</div>
                  <div className="step-content">
                    <b>{String(s.event_type)} · {String(s.method)} {String(s.path)}</b>
                    <p>{JSON.stringify(s.details)}</p>
                    <small>Aktor: {String(s.actor_id ?? 'system')} · status {String(s.status_code)}</small>
                  </div>
                </div>
              ))}
              {!(traceResult.audit_events as Array<unknown>).length && <div className="empty-state">Tidak ada audit event untuk correlation ID ini.</div>}
            </div>
            <pre className="trace-decision-output">{JSON.stringify({ model_inputs: traceResult.model_inputs, decision_output: traceResult.decision_output, human_intervention: traceResult.human_intervention }, null, 2)}</pre>
          </div>
        )}
      </article>}

      {/* 2. Model Drift Monitoring Table */}
      <article className="panel table-panel">
        <div className="panel-heading">
          <div>
            <div className="panel-kicker">MODEL DRIFT MONITORING (ML SCHEMAS)</div>
            <h2>Status Stabilitas Model (PSI Metrics)</h2>
          </div>
        </div>
        <table className="campaign-table">
          <thead>
            <tr>
              <th>Nama Model AI</th>
              <th>Metrik</th>
              <th>Nilai Terukur (PSI)</th>
              <th>Ambang Batas (Threshold)</th>
              <th>Status Kesehatan</th>
            </tr>
          </thead>
          <tbody>
            {data.drift.map((metric, index) => <tr key={`${metric.model}-${index}`}><td><b>{String(metric.model ?? 'model')}</b></td><td>{String(metric.metric ?? 'metric')}</td><td>{String(metric.value)}</td><td>{String(metric.threshold)}</td><td><span className={`tier-badge ${metric.status === 'healthy' ? 'tier-platinum' : 'tier-gold'}`}>{String(metric.status)}</span></td></tr>)}
          </tbody>
        </table>
        {!data.drift.length && <div className="empty-state">Belum ada metrik model drift dari API.</div>}
      </article>

      <article className="panel table-panel">
        <div className="panel-heading"><div><div className="panel-kicker">OBSERVED VS INCREMENTAL</div><h2>Campaign measurement</h2></div></div>
        <table className="campaign-table"><thead><tr><th>Campaign ID</th><th>Metric</th><th>Observed</th><th>Incremental</th></tr></thead><tbody>{data.campaign_measurements.map((item, index) => <tr key={`${item.campaign_id}-${index}`}><td>{String(item.campaign_id)}</td><td>{String(item.metric)}</td><td>{String(item.observed)}</td><td>{String(item.incremental)}</td></tr>)}</tbody></table>
        {!data.campaign_measurements.length && <div className="empty-state">Belum ada hasil pengukuran campaign dari API.</div>}
      </article>

      <article className="panel table-panel monitor-audit-panel">
        <div className="panel-heading"><div><div className="panel-kicker">GOVERNANCE EVENT LOG</div><h2>Audit dan pipeline terbaru</h2></div></div>
        <div className="audit-table">
          <div className="audit-table-head"><span>EVENT / RUN</span><span>STATUS</span><span>CORRELATION / RUN ID</span><span>TRACE</span></div>
          {data.audit.map((event, index) => <div className="audit-table-row" key={`audit-${index}`}><b>{String(event.event_type)}</b><span>{String(event.status_code)}</span><code>{String(event.correlation_id)}</code>{canTrace ? <button aria-label={`Gunakan trace ${String(event.correlation_id)}`} onClick={() => { setTraceId(String(event.correlation_id)); window.scrollTo({ top: 0, behavior: 'smooth' }) }}><ArrowRight size={14} /></button> : <span>Restricted</span>}</div>)}
          {data.pipeline_runs.map((run, index) => <div className="audit-table-row" key={`pipeline-${index}`}><b>pipeline run</b><span>{String(run.status)}</span><code>{String(run.id)}</code><span>{String(run.started_at)}</span></div>)}
        </div>
        {!data.audit.length && !data.pipeline_runs.length && <div className="empty-state">Belum ada audit event atau pipeline run.</div>}
      </article>
    </section>
  </>
}

function CampaignBuilder({ customers, onClose, onSave }: { customers: Customer[]; onClose: () => void; onSave: (name: string, segment: string, channel: string, draft: string) => void }) {
  const [name, setName] = useState('')
  const segments = [...new Set(customers.map((customer) => customer.city).filter(Boolean))]
  const [segment, setSegment] = useState(segments[0] ?? '')
  const [channel, setChannel] = useState('WhatsApp')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (name.trim().length < 3) { setError('Masukkan nama kampanye minimal 3 karakter.'); return }
    if (!segment) { setError('Muat atau pilih segmen customer yang tersedia sebelum membuat campaign.'); return }
    if (draft.trim().length < 5) { setError('Tulis draf pesan minimal 5 karakter agar dapat ditinjau approver.'); return }
    onSave(name.trim(), segment, channel, draft.trim())
  }

  return (
    <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="builder-modal" role="dialog" aria-modal="true" aria-labelledby="builder-title">
        <div className="builder-header">
          <div>
            <span className="builder-icon"><Sparkles size={18} /></span>
            <div>
              <div className="eyebrow">CAMPAIGN STUDIO</div>
              <h2 id="builder-title">Buat Kampanye Baru</h2>
            </div>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close campaign builder"><X size={19} /></button>
        </div>

        <form onSubmit={submit}>
          <div className="builder-body">
            <div className="builder-fields">
              <label className="field-label">
                Nama Kampanye
                <input autoFocus value={name} onChange={(e) => { setName(e.target.value); setError('') }} placeholder="Contoh: Ramadan Skin Renewal 2026" />
              </label>

              <label className="field-label">
                Target Segmen Pelanggan
                <select value={segment} onChange={(e) => setSegment(e.target.value)}>
                  <option value="">Pilih segmen customer</option>
                  {segments.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>

              <label className="field-label">
                Channel Delivery (Channel Simulator)
                <select value={channel} onChange={(e) => setChannel(e.target.value)}>
                  <option>WhatsApp</option>
                  <option>Email</option>
                  <option>In-app</option>
                  <option>SMS</option>
                </select>
              </label>

              <label className="field-label">
                Draf Pesan Kampanye (Persetujuan Draf)
                <textarea 
                  value={draft} 
                  onChange={(e) => setDraft(e.target.value)} 
                  required
                  minLength={5}
                  placeholder="Tulis draf pesan penawaran yang akan direview oleh Campaign Manager..." 
                  rows={3} 
                />
              </label>

              {error && <p className="field-error">{error}</p>}
            </div>

            <aside className="builder-preview">
              <div className="preview-top">
                <div className="preview-label">ESTIMASI AUDIENS TERJANGKAU</div>
                <div className="preview-count">Server-side <small>audience estimate</small></div>
                <p>Audiens dan consent untuk {channel} akan divalidasi oleh service sebelum eksekusi.</p>
              </div>
              <div className="preview-safety">
                <ShieldCheck size={15} /> Menggunakan Channel Simulator Murni (T-SEC-03 Compliant)
              </div>
            </aside>
          </div>

          <div className="builder-footer">
            <span><ShieldCheck size={15} /> Disimpan sebagai Draf untuk alur Human Approval.</span>
            <div>
              <button type="button" className="button button-secondary" onClick={onClose}>Batal</button>
              <button type="submit" className="button button-primary"><Check size={15} /> Simpan Draf Kampanye</button>
            </div>
          </div>
        </form>
      </section>
    </div>
  )
}

function LoadingScreen() {
  return <main className="login-shell"><div className="login-panel loading-panel"><span className="brand-mark"><span /><span /><span /></span><h1>VTEKI Intelligence</h1><p>Memverifikasi sesi dan memuat data platform…</p><div className="loading-line"><i /></div></div></main>
}

function LoginScreen({ onLogin, error }: { onLogin: (email: string, password: string) => Promise<void>; error: string }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [loginError, setLoginError] = useState('')
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setLoginError('')
    try {
      await onLogin(email, password)
    } catch (loginFailure) {
      setLoginError(loginFailure instanceof Error ? loginFailure.message : 'Login gagal.')
    } finally {
      setSubmitting(false)
    }
  }
  return <main className="login-shell">
    <div className="login-aside"><span className="login-ornament ornament-a" /><span className="login-ornament ornament-b" /><div className="login-brand"><span className="brand-mark"><span /><span /><span /></span><b>vteki<span>.</span></b></div><div className="login-aside-copy"><small>CUSTOMER INTELLIGENCE PLATFORM</small><h1>Decisions with<br />a clear lineage.</h1><p>Secure access to customer profiles, campaign governance, and decision traceability.</p></div><div className="login-aside-foot"><ShieldCheck size={15} /> Role-based access · Audited workflows</div></div>
    <section className="login-panel"><div className="login-form-heading"><span className="eyebrow">SECURE WORKSPACE</span><h2>Masuk ke platform</h2><p>Gunakan akun yang dibuat administrator untuk melanjutkan.</p></div><form onSubmit={submit}><label className="field-label">Email<input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="nama@organisasi.id" /></label><label className="field-label">Password<input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>{(loginError || error) && <p className="field-error">{loginError || error}</p>}<button className="button button-primary login-submit" type="submit" disabled={submitting}>{submitting ? 'Memverifikasi…' : 'Masuk'}<ArrowRight size={15} /></button></form><div className="login-security"><ShieldCheck size={15} /><span>JWT session · role permissions · append-only audit</span></div></section>
  </main>
}

function TierBadge({ tier }: { tier: Customer['tier'] }) { return <span className={`tier-badge tier-${tier.toLowerCase()}`}><i />{tier}</span> }
function StatusBadge({ status }: { status: Campaign['status'] }) { return <span className={`status-badge status-${status.toLowerCase().replace(' ', '-')}`}><i />{status}</span> }

export default App