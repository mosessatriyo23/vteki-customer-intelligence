import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight,
  Bell,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
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
  Menu,
  PanelLeftClose,
  Eye,
  EyeOff,
} from 'lucide-react'
import { api, ApiError, getStoredToken, storeToken } from './api'
import { GoldenSnapshotsPanel } from './GoldenSnapshotsPanel'
import type { ApiAuditEvent, ApiCampaign, ApiCustomer, ApiDecision, ApiModelPredictionRecord, ApiModelPredictionRun, ApiReview, ApiUser } from './api'

type Page = 'dashboard' | 'customers' | 'campaigns' | 'reviews' | 'decisions' | 'monitoring' | 'governance' | 'models'

const pagePaths: Record<Page, string> = {
  dashboard: '/', customers: '/customers', campaigns: '/campaigns', reviews: '/identity-reviews',
  decisions: '/decisions', monitoring: '/monitoring', governance: '/governance', models: '/models',
}
function pageFromPath(path: string): Page {
  const normalized = path.replace(/\/$/, '') || '/'
  return (Object.entries(pagePaths) as Array<[Page, string]>).find(([, route]) => route === normalized)?.[0] ?? 'dashboard'
}

type Customer = {
  apiId: number
  id: string
  name: string
  initials: string
  segment: string
  value: string
  ltv: number | null
  churnRisk: string | null
  goldenCustomerId: string | null
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
  status: 'Unknown' | 'Draft' | 'Scheduled' | 'Running' | 'Pending approval' | 'Approved' | 'Rejected' | 'Completed' | 'Failed'
  reach: string
  color: string
  messageDraft?: string
  executionStatus?: string
  executionSummary?: string
  nbaDecisionId?: number | null
  targetCustomerId?: number | null
  latestMeasurement?: ApiCampaign['latest_measurement']
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
  customerApiId: number
  customer: string
  recommendation: string
  rationale: string
  status: 'Proposed' | 'Overridden' | 'Evaluated'
  selected?: string
  reason?: string
  engineVersion?: string
  noActionReason?: string | null
}

function mapCustomer(row: ApiCustomer): Customer {
  const colors = ['coral', 'teal', 'blue', 'yellow'] as const
  return {
    apiId: row.id,
    id: row.customer_code,
    name: row.full_name,
    initials: row.full_name.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase(),
    segment: row.segment,
    value: row.ltv === null ? 'Belum tersedia' : new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(row.ltv),
    ltv: row.ltv,
    churnRisk: row.churn_risk,
    goldenCustomerId: row.golden_customer_id,
    lastSeen: new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium' }).format(new Date(row.created_at)),
    email: row.email,
    phone: '—',
    since: new Intl.DateTimeFormat('id-ID', { month: 'short', year: 'numeric' }).format(new Date(row.created_at)),
    visits: '—',
    nextBest: row.next_best_action ?? 'Belum ada rekomendasi',
    color: colors[row.id % colors.length],
  }
}

function mapCampaign(row: ApiCampaign): Campaign {
  const statusMap: Record<string, Campaign['status']> = {
    Draft: 'Draft', PendingApproval: 'Pending approval', Approved: 'Approved', Rejected: 'Rejected', Completed: 'Completed',
  }
  const executionResult = row.latest_execution?.result
  const audience = executionResult?.audience_size
  const variantA = executionResult?.variant_a_count
  const variantB = executionResult?.variant_b_count
  const executionStatus = row.latest_execution?.status
  const status: Campaign['status'] = row.status === 'Active'
    ? (executionStatus === 'completed' ? 'Completed'
      : executionStatus === 'failed' || executionStatus === 'cancelled' ? 'Failed'
        : executionStatus === 'running' || executionStatus === 'cancel_requested' ? 'Running'
          : executionStatus === 'queued' ? 'Scheduled' : 'Unknown')
    : statusMap[row.status] ?? 'Unknown'
  const executionSummary = typeof audience === 'number'
    ? `${audience.toLocaleString('id-ID')} pelanggan · A ${typeof variantA === 'number' ? variantA.toLocaleString('id-ID') : '—'} / B ${typeof variantB === 'number' ? variantB.toLocaleString('id-ID') : '—'} · ${executionStatus === 'completed' ? 'simulasi selesai' : `job ${executionStatus ?? 'antrean'}`}`
    : executionStatus === 'failed'
      ? 'Simulasi gagal'
      : executionStatus
        ? `Simulasi ${executionStatus}`
        : undefined
  return {
    apiId: row.id,
    name: row.name,
    segment: row.target_segment,
    channel: `${row.channel} (Simulator)`,
    status,
    reach: typeof audience === 'number' ? audience.toLocaleString('id-ID') : 'Belum dihitung',
    color: ['coral', 'teal', 'blue', 'yellow'][row.id % 4],
    messageDraft: row.message_draft ?? '',
    executionStatus,
    executionSummary,
    nbaDecisionId: row.nba_decision_id,
    targetCustomerId: row.target_customer_id,
    latestMeasurement: row.latest_measurement,
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
  const explanation = row.rationale.reason
  return {
    apiId: row.id,
    id: `NBA-${row.id}`,
    customerApiId: row.customer_id,
    customer: `${row.customer_name} · ${row.customer_code}`,
    recommendation: row.recommended_action,
    rationale: typeof explanation === 'string' && explanation.trim() ? explanation : 'Alasan belum tersedia',
    status: row.status === 'overridden' ? 'Overridden' : row.status === 'accepted' ? 'Evaluated' : 'Proposed',
    selected: row.selected_action ?? undefined,
    reason: row.override_reason ?? undefined,
    engineVersion: typeof row.rationale.engine_version === 'string' ? row.rationale.engine_version : undefined,
    noActionReason: typeof row.rationale.no_action_reason === 'string' ? row.rationale.no_action_reason : null,
  }
}

function App() {
  const [page, setPageState] = useState<Page>(() => pageFromPath(window.location.pathname))
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const [token, setToken] = useState<string | null>(() => getStoredToken())
  const [user, setUser] = useState<ApiUser | null>(null)
  const [authLoading, setAuthLoading] = useState(() => Boolean(getStoredToken()))
  const [dataLoading, setDataLoading] = useState(false)
  const [apiError, setApiError] = useState('')
  const [customerRows, setCustomerRows] = useState<Customer[]>([])
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)
  const [search, setSearch] = useState('')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [reviews, setReviews] = useState<IdentityReview[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [monitoringData, setMonitoringData] = useState<{ drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }>({ drift: [], campaign_measurements: [], audit: [], pipeline_runs: [] })
  const [builderOpen, setBuilderOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [provenance, setProvenance] = useState<Record<string, unknown> | null>(null)

  function setPage(next: Page) {
    if (next !== page || window.location.pathname !== pagePaths[next]) window.history.pushState({ page: next }, '', pagePaths[next])
    setPageState(next)
    setMobileNavOpen(false)
  }

  useEffect(() => {
    const syncRoute = () => {
      const normalized = window.location.pathname.replace(/\/$/, '') || '/'
      const next = pageFromPath(normalized)
      if (!Object.values(pagePaths).includes(normalized)) window.history.replaceState({ page: 'dashboard' }, '', pagePaths.dashboard)
      setPageState(next)
      setMobileNavOpen(false)
    }
    window.addEventListener('popstate', syncRoute)
    const normalized = window.location.pathname.replace(/\/$/, '') || '/'
    if (!Object.values(pagePaths).includes(normalized)) window.history.replaceState({ page, }, '', pagePaths[page])
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  useEffect(() => {
    if (!mobileNavOpen) return
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setMobileNavOpen(false) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [mobileNavOpen])

  async function refreshWorkspace(sessionToken: string, roles: string[]) {
    const canLoadReviews = roles.some((role) => ['admin', 'operator'].includes(role))
    const reviewRequest = canLoadReviews
      ? api.reviews(sessionToken)
      : Promise.resolve([] as Awaited<ReturnType<typeof api.reviews>>)

    const [customerData, campaignData, reviewData, decisionData, monitoring] = await Promise.all([
      api.customers(sessionToken),
      api.campaigns(sessionToken),
      reviewRequest,
      api.decisions(sessionToken),
      api.monitoring(sessionToken),
    ])

    const mappedCustomers = customerData.map(mapCustomer)
    setCustomerRows(mappedCustomers)

    const activeCustomer =
      mappedCustomers.find((customer) => customer.apiId === selectedCustomer?.apiId) ??
      mappedCustomers[0] ??
      null

    setSelectedCustomer(activeCustomer)
    setProvenance(
      activeCustomer
        ? await api.customerProvenance(sessionToken, activeCustomer.apiId)
        : null,
    )
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
        await refreshWorkspace(token, currentUser.roles)
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

  useEffect(() => {
    if (!token || !campaigns.some((campaign) => ['queued', 'running'].includes(campaign.executionStatus ?? ''))) return
    const timer = window.setInterval(() => {
      void api.campaigns(token).then((rows) => setCampaigns(rows.map(mapCampaign))).catch(() => undefined)
    }, 2500)
    return () => window.clearInterval(timer)
  }, [token, campaigns])

  const filteredCustomers = useMemo(
    () => customerRows.filter((customer) => `${customer.name} ${customer.segment} ${customer.id}`.toLowerCase().includes(search.toLowerCase())),
    [customerRows, search],
  )

  async function handleLogin(email: string, password: string) {
    const result = await api.login(email, password)
    setUser(null)
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

  async function saveCampaign(name: string, segment: string, channel: string, messageDraft: string, nbaDecisionId: number | null) {
    if (!token) return
    try {
      const simulatorChannel = `${channel.toLowerCase().replace(/[^a-z]+/g, '_').replace(/^_|_$/g, '')}_sim`
      await api.createCampaign(token, { name, target_segment: segment, channel: simulatorChannel, message_draft: messageDraft, nba_decision_id: nbaDecisionId })
      await refreshWorkspace(token, user?.roles ?? [])
      setBuilderOpen(false)
      setPage('campaigns')
      setNotice(`Kampanye "${name}" tersimpan sebagai draf${nbaDecisionId ? ` dari NBA-${nbaDecisionId}` : ''}. Persetujuan manusia tetap diperlukan.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat kampanye.')
    }
  }

  async function transitionCampaign(campaignId: number, status: Campaign['status']) {
    if (!token) return
    const campaign = campaigns.find((item) => item.apiId === campaignId)
    if (!campaign) return
    const name = campaign.name
    let successNotice = `Status kampanye "${name}" diperbarui menjadi ${status}.`
    try {
      if (campaign.status === 'Draft' && status === 'Pending approval') await api.submitCampaign(token, campaign.apiId)
      else if (campaign.status === 'Pending approval' && status === 'Approved') await api.approveCampaign(token, campaign.apiId)
      else if (campaign.status === 'Pending approval' && status === 'Rejected') await api.rejectCampaign(token, campaign.apiId, 'Ditolak melalui review workflow')
      else if (campaign.status === 'Approved' && status === 'Scheduled') {
        const launched = await api.launchCampaign(token, campaign.apiId)
        successNotice = `Simulasi masuk antrean worker sebagai job #${launched.batch_job_id}.`
      }
      await refreshWorkspace(token, user?.roles ?? [])
      setNotice(successNotice)
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

  async function resolveIdentityReview(id: string, approved: boolean) {
    if (!token) return
    const review = reviews.find((item) => item.id === id)
    if (!review) return
    try {
      await api.resolveReview(token, review.apiId, approved, 'Keputusan reviewer pada antrean manual')
      await refreshWorkspace(token, user?.roles ?? [])
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
      await refreshWorkspace(token, user?.roles ?? [])
      setNotice(`Human override ${id} tersimpan dan tercatat di audit.`)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal menyimpan human override.')
    }
  }

  async function createIdentityReview(subject: string, candidates: string[], confidence: number, reason: string) {
    if (!token) return
    try {
      await api.createReview(token, { subject_reference: subject, candidate_references: candidates, confidence, reason })
      await refreshWorkspace(token, user?.roles ?? [])
      setNotice('Kasus identity review tersimpan di antrean.')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat kasus identity review.')
    }
  }

  async function createNBARecommendation(customerId: number, action: string, rationale: Record<string, unknown>) {
    if (!token) return
    try {
      await api.createDecision(token, { customer_id: customerId, recommended_action: action, rationale })
      await refreshWorkspace(token, user?.roles ?? [])
      setNotice('Rekomendasi NBA tersimpan dan dapat ditinjau.')
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal membuat rekomendasi NBA.')
    }
  }

  async function evaluateNBA(customerId: number) {
    if (!token) return
    try {
      const result = await api.evaluateDecision(token, customerId)
      await refreshWorkspace(token, user?.roles ?? [])
      const explanation = result.selected_action === 'NO_ACTION'
        ? `NBA memilih NO_ACTION karena data consent, skor serving, atau input kelayakan belum tersedia. Engine ${result.engine_version}.`
        : `NBA menghasilkan ${result.selected_action} dengan engine ${result.engine_version}.`
      setNotice(explanation)
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Gagal menjalankan evaluasi NBA.')
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
      {mobileNavOpen && <button className="mobile-nav-backdrop" aria-label="Tutup navigasi" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${sidebarCollapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'sidebar-open' : ''}`} aria-label="Navigasi aplikasi">
        <div className="brand-lockup">
          <span className="brand-mark"><span /><span /><span /></span>
          <span>vteki<span className="brand-dot">.</span></span>
          <button className="sidebar-collapse" aria-label={sidebarCollapsed ? 'Perluas navigasi' : 'Ciutkan navigasi'} title={sidebarCollapsed ? 'Perluas navigasi' : 'Ciutkan navigasi'} onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}><PanelLeftClose size={17} /></button>
        </div>
        
        <div className="workspace-switch">
          <span className="workspace-icon">V</span>
          <span className="workspace-copy">
            <b>Customer Intelligence</b>
            <small>Workspace</small>
          </span>
          <ChevronDown size={15} />
        </div>

        <div className="persona-box">
          <div className="persona-label">ROLE AKTIF DARI SERVER</div>
          <div className="role-list">{user.roles.map((role) => <span className="role-chip" key={role}>{role}</span>)}</div>
        </div>

        <div className="nav-label">NAVIGASI UTAMA</div>
        <nav className="main-nav" aria-label="Main navigation">
          <NavItem active={page === 'dashboard'} icon={<LayoutDashboard size={18} />} label="Ringkasan" onClick={() => setPage('dashboard')} />
          <NavItem active={page === 'customers'} icon={<UsersRound size={18} />} label="Customer 360" onClick={() => setPage('customers')} count={customerRows.length ? `${customerRows.length}` : undefined} />
          <NavItem active={page === 'campaigns'} icon={<Send size={18} />} label="Kampanye & Persetujuan" onClick={() => setPage('campaigns')} count={campaigns.filter(c => c.status === 'Pending approval').length ? `${campaigns.filter(c => c.status === 'Pending approval').length}` : undefined} />
          <NavItem active={page === 'reviews'} icon={<ClipboardCheck size={18} />} label="Manual Review Identitas" onClick={() => setPage('reviews')} count={reviews.filter(r => r.status === 'Pending').length ? `${reviews.filter(r => r.status === 'Pending').length}` : undefined} />
          <NavItem active={page === 'decisions'} icon={<Sparkles size={18} />} label="Proposal Tindakan" onClick={() => setPage('decisions')} />
          <NavItem active={page === 'monitoring'} icon={<ChartNoAxesCombined size={18} />} label="Pemantauan & Audit" onClick={() => setPage('monitoring')} />
          {user.roles.some((role) => ['admin', 'analyst'].includes(role)) && <NavItem active={page === 'models'} icon={<ChartNoAxesCombined size={18} />} label="Review model Moses" onClick={() => setPage('models')} />}
        </nav>

        <div className="nav-label tools-label">GOVERNANCE & NFR</div>
        <nav className="main-nav" aria-label="Governance">
          <NavItem active={page === 'governance'} icon={<ShieldCheck size={18} />} label="Governance, RBAC & Audit" onClick={() => setPage('governance')} />
          <NavItem active={false} icon={<WalletCards size={18} />} label="Customer 360 & Golden ID" onClick={() => setPage('customers')} />
        </nav>

        <div className="sidebar-spacer" />
        <div className="sidebar-bottom">
          <button className="plain-nav" onClick={() => setPage('governance')}><CircleHelp size={17} /> Keamanan & peran</button>
          <button className="plain-nav" onClick={logout}><LogOut size={17} /> Keluar</button>
          <div className="profile-row">
          <div className="avatar avatar-dark">{user.email.slice(0, 2).toUpperCase()}</div>
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
            <button className="mobile-menu-button icon-button" aria-label="Buka navigasi" aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen(true)}><Menu size={19} /></button>
            <span>Workspace</span>
            <span className="crumb-slash">/</span>
            <b>{pageTitle(page)}</b>
          </div>
          <div className="top-actions">
            <button className="global-search" onClick={() => setPage('customers')}>
              <Search size={16} />
              <span>Cari pelanggan</span>
            </button>
            <button className="icon-button notification-button" aria-label="Buka pemantauan" onClick={() => setPage('monitoring')}>
              <Bell size={18} />
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
              canManageCampaigns={canManageCampaigns}
              onOpenCustomers={() => setPage('customers')} 
              onNewCampaign={() => setBuilderOpen(true)} 
              onNavigate={(p) => setPage(p)}
            />
          )}
          {page === 'customers' && <><CustomerPage customers={filteredCustomers} selected={selectedCustomer} provenance={provenance} onSelect={selectCustomer} search={search} onSearch={setSearch} /><GoldenSnapshotsPanel token={token} canReview={user.roles.includes('admin') || user.roles.includes('analyst')} /></>}
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
              onEvaluate={evaluateNBA}
              canCreate={canCreateNBA}
              canOverride={canOverrideNBA}
            />
          )}
          {page === 'monitoring' && <MonitoringPage token={token ?? ''} data={monitoringData} canTrace={canTrace} />}
          {page === 'governance' && <GovernancePage token={token} user={user} />}
          {page === 'models' && (user.roles.some((role) => ['admin', 'analyst'].includes(role))
            ? <ModelPredictionReviewPage token={token} userId={user.id} canLinkIdentity={user.roles.includes('admin')} />
            : <section className="panel access-state"><ShieldCheck size={22} /><h2>Akses terbatas</h2><p>Review model tersedia untuk pengguna dengan peran admin atau analyst.</p></section>)}
        </main>
      </div>

      {builderOpen && <CampaignBuilder customers={customerRows} decisions={decisions} onClose={() => setBuilderOpen(false)} onSave={saveCampaign} />}
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
    dashboard: 'Ringkasan operasional',
    customers: 'Customer 360 & Data Provenance',
    campaigns: 'Campaign Studio & Approval Workflow',
    reviews: 'Antrean Manual Review Identitas',
    decisions: 'Layar Eksekusi NBA & Human Override',
    monitoring: 'Dashboard Monitoring, Drift & Audit Trace',
    governance: 'Governance, RBAC & Audit Trail',
    models: 'Review output model Moses',
  }[page]
}

function explainPredictionReason(reason: Record<string, unknown>): string {
  const code = typeof reason.code === 'string' ? reason.code : 'Kode alasan'
  const direction = reason.direction === 'INCREASES_RISK'
    ? 'menaikkan risiko dalam perhitungan'
    : reason.direction === 'DECREASES_RISK'
      ? 'menurunkan risiko dalam perhitungan'
      : 'arah pengaruhnya belum tersedia'
  const contribution = reason.log_odds_contribution
  if (typeof contribution !== 'number' || !Number.isFinite(contribution)) return `${code}: ${direction}.`
  const formatted = `${contribution > 0 ? '+' : ''}${contribution.toFixed(3)}`
  return `${code} ${direction} (kontribusi log-odds ${formatted}).`
}

function NavItem({ active, icon, label, count, onClick }: { active: boolean; icon: React.ReactNode; label: string; count?: string; onClick: () => void }) {
  return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick} title={label} aria-current={active ? 'page' : undefined}>{icon}<span>{label}</span>{count && <small>{count}</small>}</button>
}

function PageHeading({ eyebrow, title, subtitle, action, className = '' }: { eyebrow: string; title: string; subtitle: string; action?: React.ReactNode; className?: string }) {
  return <div className={`page-heading ${className}`}><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <div className="heading-action">{action}</div>}</div>
}

function Dashboard({ campaigns, customers: customerRows, reviews, decisions, monitoring, canManageCampaigns, onOpenCustomers, onNewCampaign, onNavigate }: { campaigns: Campaign[]; customers: Customer[]; reviews: IdentityReview[]; decisions: Decision[]; monitoring: { drift: Array<Record<string, unknown>>; campaign_measurements: Array<Record<string, unknown>>; audit: Array<Record<string, unknown>>; pipeline_runs: Array<Record<string, unknown>> }; canManageCampaigns: boolean; onOpenCustomers: () => void; onNewCampaign: () => void; onNavigate: (p: Page) => void }) {
  const measurements = monitoring.campaign_measurements
  const driftMetrics = monitoring.drift
  const pipelineRun = monitoring.pipeline_runs[0]
  const driftValue = driftMetrics.length ? Math.max(...driftMetrics.map((item) => Number(item.value ?? 0))) : null
  const pipelineLabel = pipelineRun ? String(pipelineRun.status) : 'Belum ada run'
  return <>
    <PageHeading 
      className="dashboard-heading"
      eyebrow="VTEKI · CUSTOMER INTELLIGENCE"
      title="Kenali pelanggan.\nAmbil langkah berikutnya."
      subtitle="Ringkasan pelanggan, persetujuan kampanye, dan aktivitas tim dalam satu tempat."
      action={
        <>
          <button className="button button-secondary" onClick={() => onNavigate('monitoring')}><FileSearch size={15} /> Lihat aktivitas</button>
          {canManageCampaigns && <button className="button button-primary" onClick={onNewCampaign}><Plus size={16} /> Buat Kampanye</button>}
        </>
      } 
    />

    <section className="metric-grid" aria-label="Ringkasan data">
      <Metric label="Pelanggan" value={customerRows.length.toLocaleString('id-ID')} change="Dari server" detail="Profil tersimpan" icon={<UsersRound size={16} />} />
      <Metric label="Perlu tinjauan" value={`${reviews.filter(r => r.status === 'Pending').length}`} change="Saat ini" detail="Review identitas" icon={<UserCheck size={16} />} />
      <Metric label="Proposal tindakan" value={`${decisions.length}`} change="Tersimpan" detail="Riwayat keputusan" icon={<Sparkles size={16} />} />
      <Metric label="Pembaruan data" value={pipelineLabel} change={pipelineRun ? 'Otomatis' : 'Belum berjalan'} detail="Status pipeline" icon={<Clock3 size={16} />} />
    </section>

    <section className="insight-grid">
      <article className="panel revenue-panel">
        <div className="panel-heading"><div><div className="panel-kicker">HASIL KAMPANYE</div><h2>Hasil tercatat</h2></div></div>
        {measurements.length ? <>
          <div className="revenue-total"><strong>{measurements.length.toLocaleString('id-ID')} hasil</strong><span className="delta">per metrik</span><small>Nilai dari metrik berbeda tidak dijumlahkan.</small></div>
          <div className="measurement-list">{measurements.slice(0, 6).map((item, index) => <div className="measurement-row" key={`${item.campaign_id}-${index}`}><span>Campaign #{String(item.campaign_id)} · {String(item.metric ?? 'Metrik')}</span><small>Teramati {String(item.observed ?? 'Kosong')} · Inkremental {String(item.incremental ?? 'Kosong')} · {item.source_mode === 'simulated' ? 'Simulasi' : 'Sumber belum terverifikasi'}</small></div>)}</div>
        </> : <div className="empty-state">Belum ada hasil observed-vs-incremental yang tercatat di API.</div>}
      </article>

      <article className="panel segment-panel">
        <div className="panel-heading"><div><div className="panel-kicker">KUALITAS MODEL</div><h2>Pergeseran data</h2></div></div>
        {driftValue !== null ? <><div className="segment-total"><strong>PSI {driftValue.toFixed(2)}</strong><span>{driftMetrics.length} model terukur</span></div><div className="segment-legend">{driftMetrics.slice(0, 4).map((item, index) => <SegmentRow key={`${item.model}-${index}`} label={String(item.model ?? 'model')} count={`PSI ${Number(item.value ?? 0).toFixed(2)}`} percent={String(item.status ?? '')} tone={index % 2 ? 'gold' : 'platinum'} />)}</div></> : <div className="empty-state">Belum ada metrik drift model di API.</div>}
        <button className="text-link" onClick={() => onNavigate('monitoring')}>Lihat detail Monitoring & Audit Log <ArrowRight size={15} /></button>
      </article>
    </section>

    <section className="bottom-grid">
      <article className="panel table-panel">
        <div className="panel-heading panel-heading-table"><div><div className="panel-kicker">TINJAUAN IDENTITAS</div><h2>Menunggu pemeriksaan</h2></div><button className="button button-quiet" onClick={() => onNavigate('reviews')}>Lihat semua <ArrowRight size={14} /></button></div>
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
        <div className="panel-heading panel-heading-table"><div><div className="panel-kicker">KAMPANYE</div><h2>Menunggu persetujuan</h2></div></div>
        <div className="mini-campaign-list">{campaigns.filter((campaign) => ['Draft', 'Pending approval', 'Approved'].includes(campaign.status)).slice(0, 3).map((campaign) => <div className="mini-campaign" key={campaign.apiId}><div className={`campaign-symbol ${campaign.color}`}><Gift size={16} /></div><div className="mini-campaign-copy"><b>{campaign.name}</b><small>{campaign.segment}</small></div><StatusBadge status={campaign.status} /></div>)}{!campaigns.some((campaign) => ['Draft', 'Pending approval', 'Approved'].includes(campaign.status)) && <div className="empty-state">Belum ada campaign yang menunggu workflow.</div>}</div>
        <button className="text-link" onClick={() => onNavigate('campaigns')}>Buka Studio Kampanye <ArrowRight size={15} /></button>
      </article>
    </section>

    <article className="panel table-panel dashboard-customer-panel">
      <div className="panel-heading panel-heading-table">
        <div><div className="panel-kicker">CUSTOMER 360</div><h2>Pelanggan terbaru</h2></div>
        <button className="button button-quiet" onClick={onOpenCustomers}>Buka Customer 360 <ArrowRight size={14} /></button>
      </div>
      {customerRows.length ? <CustomerTable rows={customerRows.slice(0, 3)} compact /> : <div className="empty-state">Belum ada customer di core.customers.</div>}
    </article>

    <div className="data-note">
      <ShieldCheck size={14} /> Pengiriman kampanye memakai simulator <span>Aktivitas tercatat di audit</span>
    </div>
  </>
}

function Metric({ label, value, change, detail, icon }: { label: string; value: string; change: string; detail: string; icon: React.ReactNode }) {
  return <article className="metric"><div className="metric-top"><span>{label}</span><i>{icon}</i></div><strong>{value}</strong><div className="metric-foot"><b>{change}</b><span>{detail}</span></div></article>
}

function SegmentRow({ label, count, percent, tone }: { label: string; count: string; percent: string; tone: string }) {
  return <div className="segment-row"><span className={`legend-dot ${tone}`} /><span className="segment-name">{label}</span><b>{count}</b><small>{percent}</small></div>
}

function CustomerPage({ customers: rows, selected, provenance, onSelect, search, onSearch }: { customers: Customer[]; selected: Customer | null; provenance: Record<string, unknown> | null; onSelect: (customer: Customer) => void; search: string; onSearch: (value: string) => void }) {
  const [segmentFilter, setSegmentFilter] = useState('all')
  const segments = [...new Set(rows.map((customer) => customer.segment))].sort()
  const visibleRows = segmentFilter === 'all' ? rows : rows.filter((customer) => customer.segment === segmentFilter)

  function exportCustomers() {
    const quote = (value: string | number | null) => `"${String(value ?? '').replaceAll('"', '""')}"`
    const csv = [
      ['customer_code', 'full_name', 'email', 'segment', 'ltv_idr', 'churn_risk', 'golden_customer_id'],
      ...visibleRows.map((customer) => [customer.id, customer.name, customer.email, customer.segment, customer.ltv, customer.churnRisk, customer.goldenCustomerId]),
    ].map((line) => line.map(quote).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob([`\uFEFF${csv}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'vteki-customers.csv'
    link.click()
    URL.revokeObjectURL(url)
  }

  return <>
    <PageHeading eyebrow="CUSTOMER DATA PLATFORM" title="Customer 360 & Provenance" subtitle="Tampilan profil, identitas Golden Customer, dan provenance yang benar-benar tersedia di API." action={<><label className="customer-filter-control"><Filter size={15} /><span className="sr-only">Filter segmen</span><select aria-label="Filter segmen" value={segmentFilter} onChange={(event) => setSegmentFilter(event.target.value)}><option value="all">Semua segmen</option>{segments.map((segment) => <option key={segment} value={segment}>{segment}</option>)}</select></label><button className="button button-primary" onClick={exportCustomers}><Download size={15} /> Ekspor CSV</button></>} />
    <div className="customer-layout">
      <section className="panel customer-list-panel">
        <div className="list-toolbar"><div className="inline-search"><Search size={16} /><input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Cari pelanggan berdasarkan kode/nama" aria-label="Search customers" /></div></div>
        <div className="customer-count"><b>{segmentFilter === 'all' ? 'Semua Pelanggan' : segmentFilter}</b><span>{visibleRows.length}</span><ChevronDown size={14} /></div>
        <CustomerTable rows={visibleRows} onSelect={onSelect} selectedId={selected?.id} />
        {visibleRows.length === 0 && <div className="empty-state">{search ? `Tidak ada pelanggan dengan kata kunci “${search}”.` : 'Belum ada customer pada filter ini.'}</div>}
        <div className="list-footer">Menampilkan {visibleRows.length} pelanggan dari API</div>
      </section>
      {selected && <CustomerProfile customer={selected} provenance={provenance} />}
    </div>
  </>
}

function CustomerTable({ rows, compact = false, onSelect, selectedId }: { rows: Customer[]; compact?: boolean; onSelect?: (customer: Customer) => void; selectedId?: string }) {
  return <div className={`customer-table-wrap ${compact ? 'compact-table' : ''}`}><table className="customer-table"><thead><tr><th>Pelanggan</th><th>Segmen</th><th>Nilai seumur hidup</th><th>Tercatat</th></tr></thead><tbody>{rows.map((customer) => <tr key={customer.id} className={selectedId === customer.id ? 'selected-row' : ''} onClick={() => onSelect?.(customer)}><td><div className="table-customer"><div className={`avatar avatar-${customer.color}`}>{customer.initials}</div><div><b>{customer.name}</b><small>{customer.id}</small></div></div></td><td><span className="segment-chip">{customer.segment}</span></td><td className="value-cell">{customer.value}</td><td className="last-active">{customer.lastSeen}</td></tr>)}</tbody></table></div>
}

function CustomerProfile({ customer, provenance }: { customer: Customer; provenance: Record<string, unknown> | null }) {
  const features = (provenance?.features as Array<Record<string, unknown>> | undefined) ?? []
  const audit = (provenance?.audit as Array<Record<string, unknown>> | undefined) ?? []
  const traces = (provenance?.decision_traces as Array<Record<string, unknown>> | undefined) ?? []
  return <aside className="panel profile-panel">
    <div className="profile-cover"><span className="cover-orbit cover-orbit-one" /><span className="cover-orbit cover-orbit-two" /><button className="more-button cover-more" aria-label="Opsi profil belum tersedia" title="Opsi profil belum tersedia" disabled><MoreHorizontal size={20} /></button><div className={`profile-avatar avatar-${customer.color}`}>{customer.initials}</div></div>
    <div className="profile-main">
      <div className="profile-name-row"><div><h2>{customer.name}</h2><span>{customer.id}</span>{customer.goldenCustomerId && <small className="golden-link-label">Golden Customer · {customer.goldenCustomerId}</small>}</div><span className="segment-chip">{customer.segment}</span></div>
      <p className="profile-location">Tercatat sejak {customer.since}</p>
      <div className="profile-actions"><button className="button button-secondary" disabled title="Tidak ada pengiriman pesan eksternal pada platform ini"><ShieldCheck size={14} /> Simulator saja</button><button className="button button-secondary" aria-label="Opsi profil belum tersedia" title="Opsi profil belum tersedia" disabled><MoreHorizontal size={17} /></button></div>
      <div className="profile-stats"><div><small>Nilai seumur hidup</small><b>{customer.value}</b></div><div><small>Total kunjungan</small><b>{customer.visits}</b></div></div>
      <div className="profile-section"><div className="profile-section-title">KONTAK TERCATAT <button aria-label="Edit kontak tidak tersedia" title="Edit kontak tidak tersedia" disabled><MoreHorizontal size={16} /></button></div><div className="contact-line"><span className="contact-icon">@</span>{customer.email}</div><div className="contact-line"><span className="contact-icon">#</span>{customer.phone}</div></div>
      <div className="profile-section"><div className="profile-section-title">REKOMENDASI TERSIMPAN <Sparkles size={15} /></div><div className="next-action"><div className="next-action-icon"><Gift size={17} /></div><div><b>{customer.nextBest || 'Belum ada rekomendasi'}</b></div></div></div>
      
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

      <div className="consent-footer"><ShieldCheck size={15} /><span>Consent detail belum tersedia dari sumber data; channel customer tetap diblokir.</span></div>
    </div>
  </aside>
}

function CampaignPage({ campaigns, canManage, onNew, onTransition }: { campaigns: Campaign[]; canManage: boolean; onNew: () => void; onTransition: (campaignId: number, status: Campaign['status']) => void }) {
  const [activeFilter, setActiveFilter] = useState('All campaigns')
  const visible = campaigns.filter((campaign) => activeFilter === 'All campaigns' || campaign.status === activeFilter)
  const runningCount = campaigns.filter((campaign) => ['Scheduled', 'Running'].includes(campaign.status)).length
  const pendingCount = campaigns.filter((campaign) => campaign.status === 'Pending approval').length

  return <>
    <PageHeading eyebrow="ENGAGEMENT & APPROVAL WORKFLOW" title="Campaign Studio & Persetujuan Draf" subtitle="Formulir pembuatan kampanye, peninjauan draf pesan, dan alur persetujuan (Human Approval Workflow)." action={canManage && <button className="button button-primary" onClick={onNew}><Plus size={16} /> Kampanye Baru</button>} />
    <div className="model-review-notice campaign-simulation-notice"><ShieldCheck size={18} /><div><b>Simulator saja</b><p>Aplikasi tidak mengirim pesan sungguhan. Persetujuan manusia diwajibkan sebelum worker menjalankan simulasi.</p></div></div>
    <section className="campaign-summary">
      <div><span>Total campaign</span><b>{campaigns.length}</b><small>Data tersimpan pada act.campaigns</small></div>
      <div><span>Simulasi berjalan</span><b>{runningCount}</b><small>Job worker aktif</small></div>
      <div><span>Menunggu approval</span><b>{pendingCount}</b><small><ShieldCheck size={14} /> Channel simulator only</small></div>
      <div className="summary-illustration"><span className="summary-ring ring-one" /><span className="summary-ring ring-two" /><span className="summary-star"><Sparkles size={21} /></span></div>
    </section>

    <div className="campaign-toolbar">
      <div className="filter-tabs">
        {['All campaigns', 'Scheduled', 'Running', 'Pending approval', 'Draft', 'Approved', 'Completed', 'Failed', 'Unknown'].map((filter) => (
          <button className={activeFilter === filter ? 'selected' : ''} onClick={() => setActiveFilter(filter)} key={filter}>
            {filter}
            <span>{filter === 'All campaigns' ? campaigns.length : campaigns.filter((c) => c.status === filter).length}</span>
          </button>
        ))}
      </div>
    </div>

    <section className="panel campaign-table-panel">
      <table className="campaign-table">
        <thead>
          <tr>
            <th>Kampanye & Draf Pesan</th>
            <th>Segmen Audiens</th>
            <th>Channel</th>
            <th>Jangkauan simulasi</th>
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
              <td>{campaign.segment}{campaign.nbaDecisionId && <small className="campaign-execution-note">Dari NBA-{campaign.nbaDecisionId} · target satu pelanggan</small>}</td>
              <td><span className="channel-pill">{campaign.channel}</span></td>
              <td>{campaign.reach}</td>
              <td><StatusBadge status={campaign.status} />{campaign.executionSummary && <small className="campaign-execution-note">{campaign.executionSummary}</small>}{campaign.latestMeasurement && <small className="campaign-execution-note">Ukur: {campaign.latestMeasurement.metric_name} · teramati {campaign.latestMeasurement.observed_value} · inkremental {campaign.latestMeasurement.incremental_value} · {campaign.latestMeasurement.source_mode === 'simulated' ? 'simulasi' : 'sumber belum terverifikasi'}</small>}</td>
              <td>
                <div className="action-button-group">
                  {!canManage ? <span className="text-muted-sm">Read only</span> : campaign.status === 'Draft' ? (
                    <button className="button-sm button-approve" onClick={() => onTransition(campaign.apiId, 'Pending approval')}>
                      <FileSearch size={13} /> Ajukan Approval
                    </button>
                  ) : campaign.status === 'Pending approval' ? (
                    <>
                      <button className="button-sm button-approve" onClick={() => onTransition(campaign.apiId, 'Approved')}>
                        <Check size={13} /> Setujui
                      </button>
                      <button className="button-sm button-reject" onClick={() => onTransition(campaign.apiId, 'Rejected')}>
                        <X size={13} /> Tolak
                      </button>
                    </>
                  ) : campaign.status === 'Approved' ? (
                    <button className="button-sm button-launch" onClick={() => onTransition(campaign.apiId, 'Scheduled')}>
                      <Send size={13} /> Peluncuran Sim
                    </button>
                  ) : (
                    <span className="text-muted-sm">{['Rejected', 'Completed', 'Failed'].includes(campaign.status) ? 'Aksi selesai' : 'Status tidak tersedia'}</span>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && <div className="empty-state">Tidak ada kampanye pada kategori ini.</div>}
      <div className="list-footer">Menampilkan {visible.length} dari {campaigns.length} kampanye dari API</div>
    </section>
  </>
}

function IdentityReviewPage({ reviews, onResolve, onCreate, canResolve }: { reviews: IdentityReview[]; onResolve: (id: string, approved: boolean) => void; onCreate: (subject: string, candidates: string[], confidence: number, reason: string) => void; canResolve: boolean }) {
  const [createOpen, setCreateOpen] = useState(false)
  const [subject, setSubject] = useState('')
  const [candidates, setCandidates] = useState('')
  const [confidence, setConfidence] = useState('')
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

function DecisionPage({ decisions, onOverride, customers: customerRows, onCreate, onEvaluate, canCreate, canOverride }: { decisions: Decision[]; onOverride: (id: string, selected: string, reason: string) => void; customers: Customer[]; onCreate: (customerId: number, action: string, rationale: Record<string, unknown>) => void; onEvaluate: (customerId: number) => void; canCreate: boolean; canOverride: boolean }) {
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null)
  const [customAction, setCustomAction] = useState('')
  const [reason, setReason] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [newCustomerId, setNewCustomerId] = useState('')
  const [newAction, setNewAction] = useState('')
  const [newReason, setNewReason] = useState('')
  const [evaluationCustomerId, setEvaluationCustomerId] = useState('')

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
      subtitle="Proposal Next-Best-Action yang tersimpan dan fasilitas Human Override manual dengan pencatatan alasannya."
      action={canCreate && <button className="button button-secondary" onClick={() => setCreateOpen((open) => !open)} disabled={!customerRows.length}><Plus size={15} /> Proposal manual</button>}
    />
    {canCreate && <form className="panel decision-create-form" onSubmit={(event) => { event.preventDefault(); const customerId = Number(evaluationCustomerId); if (!customerId) return; onEvaluate(customerId) }}><div><div className="panel-kicker">EVALUASI PERSISTEN · CHRIS NBA ENGINE</div><p className="empty-state">Menjalankan engine pada customer terpilih. Input yang belum tersedia akan diblokir dan dicatat, bukan diisi dengan angka contoh.</p></div><label className="field-label">Pelanggan<select required value={evaluationCustomerId} onChange={(event) => setEvaluationCustomerId(event.target.value)}><option value="">Pilih customer</option>{customerRows.map((customer) => <option key={customer.apiId} value={customer.apiId}>{customer.name} · {customer.id}</option>)}</select></label><button className="button button-primary" type="submit" disabled={!customerRows.length}>Jalankan evaluasi NBA</button></form>}
    {createOpen && <form className="panel decision-create-form" onSubmit={(event) => { event.preventDefault(); const customer = customerRows.find((item) => item.apiId === Number(newCustomerId)); if (!customer || !newAction.trim() || newReason.trim().length < 5) return; onCreate(customer.apiId, newAction.trim(), { source: 'manual', reason: newReason.trim() }); setCreateOpen(false); setNewAction(''); setNewReason('') }}><div className="field-full"><b>Proposal manual</b><small>Ditulis pengguna, bukan hasil model atau evaluasi Chris NBA Engine.</small></div><label className="field-label">Pelanggan<select required value={newCustomerId} onChange={(event) => setNewCustomerId(event.target.value)}><option value="">Pilih customer</option>{customerRows.map((customer) => <option key={customer.apiId} value={customer.apiId}>{customer.name} · {customer.id}</option>)}</select></label><label className="field-label">Tindakan yang diusulkan<input required value={newAction} onChange={(event) => setNewAction(event.target.value)} placeholder="Tulis proposal untuk ditinjau" /></label><label className="field-label">Alasan<textarea required minLength={5} rows={3} value={newReason} onChange={(event) => setNewReason(event.target.value)} placeholder="Jelaskan alasan proposal manual." /></label><button className="button button-primary" type="submit">Simpan proposal manual</button></form>}
    <div className="decision-grid">
      {decisions.map(d => (
        <article className="panel decision-card" key={d.id}>
          <div className="decision-header">
            <div>
              <span className="nba-id">{d.id}</span>
              <h3>{d.customer}</h3>
            </div>
            <span className={`status-badge ${d.status === 'Overridden' ? 'status-scheduled' : d.status === 'Evaluated' ? 'status-rejected' : 'status-live'}`}>{d.status === 'Evaluated' ? 'Dievaluasi · NO_ACTION' : d.status}</span>
          </div>

          <div className="decision-body">
            <div className="nba-box">
              <div className="nba-label">{d.status === 'Evaluated' ? 'HASIL ENGINE:' : 'PROPOSAL NEXT-BEST-ACTION:'}</div>
              <div className="nba-text"><Sparkles size={16} /> {d.recommendation}</div>
              <small>{d.rationale}</small>
              {d.engineVersion && <small>Engine {d.engineVersion} · serving belum diaktifkan · NO_ACTION tidak dapat dipakai untuk kampanye.</small>}
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
              <h2 id="builder-title">Ubah proposal tindakan</h2>
              <p>Catat tindakan baru dan alasan perubahannya untuk {selectedDecision.customer}</p>
            </div>
            <button className="icon-button" onClick={() => setSelectedDecision(null)}><X size={18} /></button>
          </div>
          <form onSubmit={handleOverrideSubmit}>
            <div className="builder-body-simple">
              <label className="field-label">
                Proposal saat ini
                <input disabled value={selectedDecision.recommendation} />
              </label>
              <label className="field-label">
                Tindakan Override Baru (Manual Action)
                <input 
                  required 
                  placeholder="Tuliskan tindakan yang dipilih"
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
              <th>Nama model</th>
              <th>Metrik</th>
              <th>Nilai Terukur (PSI)</th>
              <th>Ambang Batas (Threshold)</th>
              <th>Status Kesehatan</th>
            </tr>
          </thead>
          <tbody>
            {data.drift.map((metric, index) => <tr key={`${metric.model}-${index}`}><td><b>{String(metric.model ?? 'model')}</b></td><td>{String(metric.metric ?? 'metric')}</td><td>{String(metric.value)}</td><td>{String(metric.threshold)}</td><td><span className={`status-badge ${metric.status === 'healthy' ? 'status-live' : 'status-scheduled'}`}>{String(metric.status)}</span></td></tr>)}
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

function ModelPredictionReviewPage({ token, userId, canLinkIdentity }: { token: string; userId: number; canLinkIdentity: boolean }) {
  const [runs, setRuns] = useState<ApiModelPredictionRun[]>([])
  const [selectedRun, setSelectedRun] = useState<ApiModelPredictionRun | null>(null)
  const [records, setRecords] = useState<ApiModelPredictionRecord[]>([])
  const [totalRecords, setTotalRecords] = useState(0)
  const [manifestFile, setManifestFile] = useState<File | null>(null)
  const [recordsFile, setRecordsFile] = useState<File | null>(null)
  const [reviewNote, setReviewNote] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [runsLoading, setRunsLoading] = useState(true)
  const [recordsLoading, setRecordsLoading] = useState(false)
  const [runsLoadFailed, setRunsLoadFailed] = useState(false)
  const [recordsLoadFailed, setRecordsLoadFailed] = useState(false)

  async function refreshRuns() {
    setRunsLoading(true)
    setRunsLoadFailed(false)
    try {
      setRuns(await api.modelPredictionRuns(token))
    } catch (failure) {
      setRunsLoadFailed(true)
      throw failure
    } finally {
      setRunsLoading(false)
    }
  }

  useEffect(() => { void refreshRuns().catch((failure) => setError(failure instanceof Error ? failure.message : 'Gagal memuat antrean model.')) }, [token])

  async function openRun(run: ApiModelPredictionRun) {
    setSelectedRun(run)
    setRecords([])
    setTotalRecords(run.record_count)
    setRecordsLoadFailed(false)
    setRecordsLoading(true)
    try {
      const page = await api.modelPredictionRecords(token, run.id)
      setRecords(page.records)
      setTotalRecords(page.total)
    } catch (failure) {
      setRecordsLoadFailed(true)
      setError(failure instanceof Error ? failure.message : 'Gagal memuat hasil model.')
    } finally {
      setRecordsLoading(false)
    }
  }

  async function importRun(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!manifestFile || !recordsFile) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const manifest = JSON.parse(await manifestFile.text()) as Record<string, unknown>
      const rawLines = (await recordsFile.text()).split(/\r?\n/).filter((line) => line.trim())
      const sourceRecords = rawLines.map((line) => JSON.parse(line) as Record<string, unknown>)
      const created = await api.importModelPredictionRun(token, manifest, sourceRecords)
      await refreshRuns()
      setManifestFile(null)
      setRecordsFile(null)
      const form = event.currentTarget
      form.reset()
      setNotice(`${created.record_count.toLocaleString('id-ID')} baris tersimpan untuk pemeriksaan independen.`)
      await openRun(created)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Berkas Moses tidak dapat diimpor.')
    } finally {
      setBusy(false)
    }
  }

  async function loadMoreRecords() {
    if (!selectedRun || records.length >= totalRecords) return
    try {
      const page = await api.modelPredictionRecords(token, selectedRun.id, records.length)
      setRecords((current) => [...current, ...page.records])
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Gagal memuat baris berikutnya.')
    }
  }

  async function reviewRun(decision: 'reviewed' | 'rejected') {
    if (!selectedRun || reviewNote.trim().length < 5) return
    setBusy(true)
    setError('')
    try {
      const updated = await api.reviewModelPredictionRun(token, selectedRun.id, decision, reviewNote.trim())
      setSelectedRun(updated)
      setReviewNote('')
      await refreshRuns()
      setNotice(decision === 'reviewed' ? 'Pemeriksaan independen tercatat.' : 'Berkas ditandai untuk ditolak.')
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Pemeriksaan tidak dapat disimpan.')
    } finally {
      setBusy(false)
    }
  }

  async function linkPredictionIdentity(record: ApiModelPredictionRecord) {
    if (!record.mapping_candidate) return
    setBusy(true)
    setError('')
    try {
      await api.linkGoldenIdentity(token, record.mapping_candidate.id, record.customer_id)
      if (selectedRun) await openRun(selectedRun)
      setNotice(`Golden ID berhasil ditautkan ke ${record.mapping_candidate.customer_code} berdasarkan source identity yang cocok.`)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Golden ID tidak dapat ditautkan.')
    } finally {
      setBusy(false)
    }
  }

  return <>
    <PageHeading eyebrow="MOSES · HASIL MODEL" title="Pemeriksaan hasil prediksi" subtitle="Impor artefak Moses, simpan hasil beserta versinya, lalu minta pemeriksaan dari orang lain." />
    <div className="model-review-notice"><ShieldCheck size={18} /><div><b>Review teknis belum berarti izin serving</b><p>Output Moses yang tersedia masih development/non-serving. Status “sudah ditinjau” mencatat pemeriksaan orang kedua saja; tidak mengaktifkan penggunaan skor di NBA. Skor juga hanya dipasangkan ke pelanggan aplikasi melalui Golden ID yang disetujui dan dipetakan secara eksplisit.</p></div></div>
    <section className="model-review-layout">
      <div className="model-review-column">
        <form className="panel model-import-panel" onSubmit={importRun}>
          <div className="panel-kicker">IMPOR DARI MOSES</div>
          <h2>Tambahkan artefak prediksi</h2>
          <p>Gunakan <code>contract_manifest.json</code> dan <code>records.jsonl</code> dari output <code>prediction_contract</code>.</p>
          <label className="field-label">Manifest berkas<input type="file" accept="application/json,.json" required onChange={(event) => setManifestFile(event.target.files?.[0] ?? null)} /></label>
          <label className="field-label">Baris prediksi<input type="file" accept="application/x-ndjson,.jsonl,.txt" required onChange={(event) => setRecordsFile(event.target.files?.[0] ?? null)} /></label>
          <button className="button button-primary" type="submit" disabled={busy || !manifestFile || !recordsFile}>{busy ? 'Menyimpan…' : 'Simpan untuk ditinjau'}</button>
        </form>
        <section className="panel model-run-panel">
          <div className="panel-heading"><div><div className="panel-kicker">VERSI & REVIEW</div><h2>Artefak tersimpan</h2></div><span className="model-count">{runs.length}</span></div>
          {runsLoading && <div className="empty-state" role="status">Memuat daftar artefak Moses…</div>}
          {!runsLoading && runsLoadFailed && <div className="empty-state" role="alert">Daftar artefak gagal dimuat. Coba muat ulang halaman.</div>}
          {!runsLoading && !runsLoadFailed && !runs.length && <div className="empty-state">Belum ada artefak Moses yang diimpor.</div>}
          {runs.map((run) => <button className={`model-run-row ${selectedRun?.id === run.id ? 'selected' : ''}`} key={run.id} onClick={() => void openRun(run)}>
            <span className="model-run-icon"><ChartNoAxesCombined size={17} /></span>
            <span className="model-run-copy"><b>{run.model_version}</b><small>{run.prediction_type} · {run.record_count.toLocaleString('id-ID')} baris · {new Date(run.imported_at).toLocaleDateString('id-ID')}</small></span>
            <span className={`model-review-status ${run.review_status}`}>{run.review_status === 'pending_review' ? 'Menunggu review' : run.review_status === 'reviewed' ? 'Sudah ditinjau' : 'Ditolak'}</span>
          </button>)}
        </section>
      </div>
      <div className="model-review-column">
        {selectedRun ? <section className="panel model-record-panel">
          <div className="panel-heading"><div><div className="panel-kicker">VERSI {selectedRun.model_version}</div><h2>Baris prediksi</h2></div><span className="model-review-status">DEVELOPMENT · NON-SERVING</span></div>
          <div className="model-lineage-grid"><div><small>Fitur</small><b>{selectedRun.feature_set_version}</b></div><div><small>Label</small><b>{selectedRun.label_version}</b></div><div><small>Produser</small><b>{selectedRun.producer_version}</b></div><div><small>Checksum manifest</small><code>{selectedRun.manifest_hash.slice(0, 16)}…</code></div></div>
          {recordsLoading ? <div className="empty-state" role="status">Memuat baris prediksi…</div> : recordsLoadFailed ? <div className="empty-state" role="alert">Baris prediksi gagal dimuat. Pilih ulang artefak atau muat ulang halaman.</div> : records.length ? <div className="model-table-wrap"><table className="model-score-table"><thead><tr><th>Golden ID & pelanggan aplikasi</th><th>Cutoff</th><th>Skor mentah</th><th>Status kontrak/review</th><th>Alasan prediksi</th></tr></thead><tbody>{records.map((record) => <tr key={record.id}><td><code>{record.customer_id}</code><small>{record.application_customer ? `${record.application_customer.customer_code} · ${record.application_customer.full_name} · identity ${record.identity_status ?? 'tidak diketahui'}` : `Tidak dipetakan ke pelanggan NBA · identity ${record.identity_status ?? 'tidak ditemukan'}`}</small>{canLinkIdentity && record.mapping_candidate && <button className="button-sm button-approve model-link-button" disabled={busy} onClick={() => void linkPredictionIdentity(record)}>Tautkan ke {record.mapping_candidate.customer_code}</button>}</td><td>{record.cutoff_at}</td><td>{record.score === null ? 'Kosong' : record.score.toFixed(4)}{record.band && <small>Band usulan: {record.band}</small>}</td><td>{record.contract_status}<small>Run: {selectedRun.review_status === 'reviewed' ? 'Sudah ditinjau' : selectedRun.review_status === 'rejected' ? 'Ditolak' : 'Menunggu review'} · non-serving</small></td><td>{record.reason_codes.length ? <ul className="model-reason-list">{record.reason_codes.map((reason, index) => <li key={`${String(reason.code ?? 'reason')}-${index}`}>{explainPredictionReason(reason)}</li>)}</ul> : 'Belum tersedia'}</td></tr>)}</tbody></table></div> : <div className="empty-state">Tidak ada baris prediksi pada artefak ini.</div>}
          <div className="model-record-footer">Menampilkan {records.length.toLocaleString('id-ID')} dari {totalRecords.toLocaleString('id-ID')} baris. Skor mentah ditampilkan untuk review; output belum boleh digunakan untuk memilih pelanggan atau membuat NBA.</div>
          {records.length < totalRecords && <button className="button button-secondary model-load-more" onClick={() => void loadMoreRecords()}>Muat 100 baris berikutnya</button>}
          <div className="model-review-form">
            <div className="panel-kicker">TINJAUAN INDEPENDEN</div>
            {selectedRun.review_status !== 'pending_review' ? <p>Ditinjau oleh pengguna #{selectedRun.reviewed_by}. Catatan: {selectedRun.review_note}</p> : selectedRun.submitted_by === userId ? <p>Run ini Anda kirim. Minta admin atau analis lain memeriksanya.</p> : <>
              <label className="field-label">Catatan pemeriksa<textarea rows={3} minLength={5} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="Catat versi, kelengkapan alasan, dan temuan pemeriksaan." /></label>
              <div className="model-review-actions"><button className="button button-secondary" disabled={busy || reviewNote.trim().length < 5} onClick={() => void reviewRun('rejected')}>Tolak artefak</button><button className="button button-primary" disabled={busy || reviewNote.trim().length < 5} onClick={() => void reviewRun('reviewed')}>Catat sudah ditinjau</button></div>
              <small>“Sudah ditinjau” hanya mencatat pemeriksaan independen; status serving tetap nonaktif.</small>
            </>}
          </div>
        </section> : <div className="panel empty-state model-select-empty">Pilih run yang tersimpan atau impor artefak Moses untuk memulai pemeriksaan.</div>}
      </div>
    </section>
    {(error || notice) && <div className={error ? 'api-alert model-page-alert' : 'sync-note model-page-alert'} role={error ? 'alert' : 'status'}>{error || notice}{error && <button onClick={() => setError('')} aria-label="Tutup pesan"><X size={15} /></button>}</div>}
  </>
}

function CampaignBuilder({ customers, decisions, onClose, onSave }: { customers: Customer[]; decisions: Decision[]; onClose: () => void; onSave: (name: string, segment: string, channel: string, draft: string, nbaDecisionId: number | null) => void }) {
  const [name, setName] = useState('')
  const segments = [...new Set(customers.map((customer) => customer.segment).filter(Boolean))]
  const [segment, setSegment] = useState(segments[0] ?? '')
  const [nbaDecisionId, setNbaDecisionId] = useState('')
  const [channel, setChannel] = useState('WhatsApp')
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const availableDecisions = decisions.filter((decision) => ['Proposed', 'Overridden'].includes(decision.status) && customers.some((customer) => customer.apiId === decision.customerApiId))

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (name.trim().length < 3) { setError('Masukkan nama kampanye minimal 3 karakter.'); return }
    if (!segment) { setError('Muat atau pilih segmen customer yang tersedia sebelum membuat campaign.'); return }
    if (draft.trim().length < 5) { setError('Tulis draf pesan minimal 5 karakter agar dapat ditinjau approver.'); return }
    onSave(name.trim(), segment, channel, draft.trim(), nbaDecisionId ? Number(nbaDecisionId) : null)
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
                <input autoFocus value={name} onChange={(e) => { setName(e.target.value); setError('') }} placeholder="Nama kampanye" />
              </label>

              <label className="field-label">
                Target Segmen Pelanggan
                <select value={segment} onChange={(e) => setSegment(e.target.value)} disabled={Boolean(nbaDecisionId)}>
                  <option value="">Pilih segmen customer</option>
                  {segments.map((value) => <option key={value} value={value}>{value}</option>)}
                </select>
              </label>

              <label className="field-label">
                Sumber rekomendasi NBA (opsional)
                <select value={nbaDecisionId} onChange={(event) => {
                  const id = event.target.value
                  setNbaDecisionId(id)
                  const decision = decisions.find((item) => item.apiId === Number(id))
                  const customer = decision && customers.find((item) => item.apiId === decision.customerApiId)
                  if (customer) setSegment(customer.segment)
                }}>
                  <option value="">Buat dari segmen</option>
                  {availableDecisions.map((decision) => <option key={decision.apiId} value={decision.apiId}>{decision.id} · {decision.customer} · {decision.recommendation}</option>)}
                </select>
                <small>{nbaDecisionId ? 'Target dibatasi ke pelanggan pada rekomendasi ini.' : 'Rekomendasi yang tersedia dapat ditautkan ke draf kampanye.'}</small>
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
                <div className="preview-label">JANGKAUAN AUDIENS</div>
                <div className="preview-count">Belum dihitung</div>
                <p>Jumlah audiens belum tersedia untuk draf ini.</p>
              </div>
              <div className="preview-safety">
                <ShieldCheck size={15} /> Hanya simulasi; pesan tidak dikirim ke luar aplikasi.
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
  const [showPassword, setShowPassword] = useState(false)
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
    <div className="login-aside"><span className="login-ornament ornament-a" /><span className="login-ornament ornament-b" /><div className="login-brand"><span className="brand-mark"><span /><span /><span /></span><b>vteki<span>.</span></b></div><div className="login-aside-copy"><small>VTEKI · CUSTOMER INTELLIGENCE</small><h1>Pahami pelanggan,<br />tentukan langkah berikutnya.</h1><p>Kelola profil, tinjau kampanye, dan telusuri keputusan dalam satu workspace.</p></div><div className="login-aside-foot"><ShieldCheck size={15} /> Akses berbasis peran · Aktivitas tercatat</div></div>
    <section className="login-panel"><div className="login-form-heading"><span className="eyebrow">RUANG KERJA AMAN</span><h2>Masuk ke platform</h2><p>Gunakan akun yang dibuat administrator untuk melanjutkan.</p></div><form onSubmit={submit}><div className="field-label"><label htmlFor="login-email">Email</label><input id="login-email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="nama@organisasi.id" /></div><div className="field-label"><label htmlFor="login-password">Kata sandi</label><div className="password-control"><input id="login-password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /><button type="button" className="password-toggle" aria-label={showPassword ? 'Sembunyikan kata sandi' : 'Tampilkan kata sandi'} onClick={() => setShowPassword((visible) => !visible)}>{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></div>{(loginError || error) && <p className="field-error" role="alert">{loginError || error}</p>}<button className="button button-primary login-submit" type="submit" disabled={submitting}>{submitting ? 'Memeriksa…' : 'Masuk'}<ArrowRight size={15} /></button></form><div className="login-security"><ShieldCheck size={15} /><span>Akses berbasis peran · Audit aktif</span></div></section>
  </main>
}

function StatusBadge({ status }: { status: Campaign['status'] }) { return <span className={`status-badge status-${status.toLowerCase().replace(' ', '-')}`}><i />{status}</span> }

function GovernancePage({ token, user }: { token: string; user: ApiUser }) {
  const canReadAudit = user.roles.some((role) => ['admin', 'analyst'].includes(role))
  const [events, setEvents] = useState<ApiAuditEvent[]>([])
  const [trace, setTrace] = useState<{ correlation_id: string; audit_events: ApiAuditEvent[]; decision_steps?: Array<Record<string, unknown>> } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function loadEvents() {
    if (!canReadAudit) return
    setBusy(true)
    try {
      setEvents(await api.auditEvents(token, 100))
      setError('')
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Gagal memuat audit trail.')
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void loadEvents() }, [token, canReadAudit])

  async function openTrace(correlationId: string) {
    try {
      setTrace(await api.auditTrace(token, correlationId))
      setError('')
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Gagal memuat correlation trace.')
    }
  }

  const scopes = [
    { name: 'Baca data pelanggan, campaign, dan rekomendasi', roles: 'admin · analyst · campaign_manager · operator' },
    { name: 'Tinjau model Moses dan baca audit detail', roles: 'admin · analyst' },
    { name: 'Putuskan manual review identitas', roles: 'admin · operator' },
    { name: 'Buat evaluasi NBA / proposal manual', roles: 'admin · analyst' },
    { name: 'Persetujuan campaign dan human override', roles: 'admin · campaign_manager' },
  ]

  return <>
    <PageHeading eyebrow="CONTROL PLANE" title="Governance, RBAC & Audit Trail" subtitle="Peran berasal dari API autentikasi; izin tetap ditegakkan server-side. Setiap mutasi dan evaluasi dapat ditelusuri lewat correlation ID." action={canReadAudit && <button className="button button-secondary" onClick={() => void loadEvents()} disabled={busy}><RotateCcw size={15} /> {busy ? 'Memuat…' : 'Muat ulang audit'}</button>} />
    <div className="governance-summary-grid">
      <article className="panel governance-summary"><span>AKUN AKTIF</span><b>{user.email}</b><small>User ID {user.id}</small></article>
      <article className="panel governance-summary"><span>ROLE DARI SERVER</span><div className="governance-role-list">{user.roles.map((role) => <span className="role-chip" key={role}>{role}</span>)}</div><small>UI hanya menampilkan aksi; API tetap menjadi sumber otorisasi.</small></article>
      <article className="panel governance-summary"><span>AUDIT ACCESS</span><b>{canReadAudit ? 'Tersedia' : 'Terbatas untuk role ini'}</b><small>{canReadAudit ? `${events.length} event terakhir dimuat dari API.` : 'Detail audit memerlukan admin atau analyst.'}</small></article>
    </div>
    <div className="governance-grid">
      <section className="panel governance-panel">
        <div className="panel-heading"><div><div className="panel-kicker">SERVER-SIDE AUTHORIZATION</div><h2>Cakupan RBAC</h2></div></div>
        <div className="governance-scope-list">{scopes.map((scope) => <div className="governance-scope" key={scope.name}><ShieldCheck size={16} /><div><b>{scope.name}</b><small>{scope.roles}</small></div></div>)}</div>
        <div className="schema-chip-list">{['core', 'identity', 'customer360', 'segmentation', 'feat', 'ml', 'dec', 'act', 'msr', 'gov'].map((schema) => <span key={schema}>{schema}</span>)}</div>
      </section>
      <section className="panel governance-panel audit-events-panel">
        <div className="panel-heading"><div><div className="panel-kicker">APPEND-ONLY EVENT STORE</div><h2>Aktivitas audit terbaru</h2></div></div>
        {!canReadAudit && <div className="empty-state">Akses baca audit dibatasi. Role aktif Anda tetap dapat menggunakan halaman operasional yang diizinkan API.</div>}
        {error && <p className="field-error" role="alert">{error}</p>}
        {canReadAudit && events.length === 0 && !busy && <div className="empty-state">Belum ada audit event tersimpan.</div>}
        {canReadAudit && events.length > 0 && <div className="governance-event-list">{events.map((event) => <article className="governance-event" key={event.id}><div><b>{event.event_type}</b><small>{event.method} {event.path} · status {event.status_code} · {new Date(event.occurred_at).toLocaleString('id-ID')}</small><code>{event.correlation_id}</code></div><button className="button button-secondary" onClick={() => void openTrace(event.correlation_id)}>Trace</button></article>)}</div>}
      </section>
    </div>
    {trace && <section className="panel governance-panel governance-trace" aria-live="polite"><div className="panel-heading"><div><div className="panel-kicker">CORRELATION TRACE</div><h2>{trace.correlation_id}</h2></div><button className="icon-button" aria-label="Tutup trace" onClick={() => setTrace(null)}><X size={17} /></button></div>{trace.audit_events.map((event) => <div className="governance-trace-row" key={event.id}><time>{new Date(event.occurred_at).toLocaleString('id-ID')}</time><b>{event.event_type}</b><span>{event.method} {event.path} · {event.status_code}</span><small>{event.entity_type ?? 'request'} {event.entity_id ?? ''}</small></div>)}{trace.decision_steps?.map((step, index) => <pre key={`step-${index}`}>{JSON.stringify(step, null, 2)}</pre>)}{trace.audit_events.length === 0 && <div className="empty-state">Tidak ada event untuk correlation ID ini.</div>}</section>}
  </>
}

export default App
