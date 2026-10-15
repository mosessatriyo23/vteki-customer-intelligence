#!/usr/bin/env python3
"""Enable local VTEKI dashboard preview, preserving API authentication.

Run from the repository root: python AKTIFKAN_PREVIEW_DASHBOARD.py
Idempotent: a second run makes no changes.
"""
from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "web" / "src" / "App.tsx"
CSS = ROOT / "web" / "src" / "styles.css"
MARKER = "// VTEKI_LOCAL_PREVIEW_ENABLED"

PREVIEW_SETUP = '''
// VTEKI_LOCAL_PREVIEW_ENABLED
// Ubah ke false ketika login wajib diterapkan kembali.
// Preview hanya menggunakan data contoh; endpoint FastAPI tetap memerlukan JWT.
const PREVIEW_ENABLED = true
const previewUser: ApiUser = { id: 0, email: 'preview@vteki.local', roles: ['preview'] }
const previewCustomers: Customer[] = [
  { apiId: 9001, id: 'DEMO-001', name: 'Pelanggan Demo Satu', initials: 'PS', city: 'Jakarta', tier: 'Platinum', value: 'Rp12.500.000', lastSeen: 'Okt 2026 (contoh)', email: 'demo1@example.invalid', phone: '—', since: 'Jan 2026', visits: 16, nextBest: 'Program loyalitas VIP', color: 'coral' },
  { apiId: 9002, id: 'DEMO-002', name: 'Pelanggan Demo Dua', initials: 'PD', city: 'Surabaya', tier: 'Gold', value: 'Rp6.700.000', lastSeen: 'Okt 2026 (contoh)', email: 'demo2@example.invalid', phone: '—', since: 'Mar 2026', visits: 9, nextBest: 'Promo retensi', color: 'teal' },
  { apiId: 9003, id: 'DEMO-003', name: 'Pelanggan Demo Tiga', initials: 'PT', city: 'Bandung', tier: 'Silver', value: 'Rp2.300.000', lastSeen: 'Okt 2026 (contoh)', email: 'demo3@example.invalid', phone: '—', since: 'Jun 2026', visits: 4, nextBest: 'Follow-up personal', color: 'yellow' },
  { apiId: 9004, id: 'DEMO-004', name: 'Pelanggan Demo Empat', initials: 'PE', city: 'Medan', tier: 'Gold', value: 'Rp7.850.000', lastSeen: 'Okt 2026 (contoh)', email: 'demo4@example.invalid', phone: '—', since: 'Feb 2026', visits: 11, nextBest: 'Rekomendasi produk', color: 'teal' },
]
const previewCampaigns: Campaign[] = [
  { apiId: 9001, name: 'Loyalty VIP (Demo)', segment: 'Platinum', channel: 'email_sim (Simulator)', status: 'Draft', reach: '120 (contoh)', color: 'coral' },
  { apiId: 9002, name: 'Win-back Oktober (Demo)', segment: 'Gold', channel: 'sms_sim (Simulator)', status: 'Pending approval', reach: '230 (contoh)', color: 'teal' },
  { apiId: 9003, name: 'Re-engagement (Demo)', segment: 'Silver', channel: 'email_sim (Simulator)', status: 'Approved', reach: '340 (contoh)', color: 'blue' },
]
const previewReviews: IdentityReview[] = [
  { apiId: 9001, id: 'IR-DEMO-01', subject: 'DEMO-001', candidates: ['DEMO-004'], confidence: 0.77, reason: 'Kemiripan data pelanggan — kasus simulasi', status: 'Pending' },
  { apiId: 9002, id: 'IR-DEMO-02', subject: 'DEMO-002', candidates: ['DEMO-003'], confidence: 0.68, reason: 'Perlu validasi identitas — kasus simulasi', status: 'Pending' },
]
const previewDecisions: Decision[] = [
  { id: 'NBA-DEMO-01', apiId: 9001, customer: 'Pelanggan Demo Satu · DEMO-001', recommendation: 'Penawaran member VIP', rationale: 'Simulasi: loyalitas tinggi', status: 'Proposed' },
  { id: 'NBA-DEMO-02', apiId: 9002, customer: 'Pelanggan Demo Dua · DEMO-002', recommendation: 'Voucher retensi', rationale: 'Simulasi: potensi churn', status: 'Proposed' },
]
const previewMonitoring = {
  drift: [
    { model: 'churn-risk (demo)', metric: 'PSI', value: 0.08, threshold: 0.2, status: 'healthy' },
    { model: 'customer-ltv (demo)', metric: 'PSI', value: 0.11, threshold: 0.2, status: 'healthy' },
  ],
  campaign_measurements: [
    { campaign_id: 'DEMO-001', metric: 'Engagement (demo)', observed: 72, incremental: 16 },
    { campaign_id: 'DEMO-002', metric: 'Conversion (demo)', observed: 54, incremental: 9 },
  ],
  audit: [],
  pipeline_runs: [{ id: 'DEMO-RUN', status: 'completed', started_at: 'Simulasi' }],
}
'''

CSS_ADD = '''
/* VTEKI_LOCAL_PREVIEW_ENABLED: banner mode presentasi tanpa API/token. */
.preview-banner {
  margin: 14px 24px 0;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  border: 1px solid #e9d59b;
  border-radius: 9px;
  background: #fff9e8;
  color: #665124;
  font-size: 12px;
}
.preview-banner strong { font-weight: 750; }
.preview-banner span { flex: 1; min-width: 190px; }
.preview-banner button {
  cursor: pointer;
  background: #234b37;
  color: white;
  border: 0;
  border-radius: 6px;
  padding: 8px 11px;
  font-size: 12px;
  font-weight: 650;
}
.preview-banner button:hover { background: #35684c; }
.preview-return {
  display: block;
  margin: 14px auto 0;
  padding: 8px;
  border: 0;
  background: transparent;
  color: #38694b;
  cursor: pointer;
}
@media (max-width: 700px) { .preview-banner { margin: 10px 12px 0; } }
'''


def repl(text: str, old: str, new: str, title: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"Gagal menemukan blok '{title}' secara unik (ketemu {count} kali). Tidak ada file yang diubah.")
    return text.replace(old, new, 1)


def main():
    if not APP.is_file() or not CSS.is_file():
        raise SystemExit("ERROR: Simpan skrip ini di folder utama project, satu folder dengan 'web'.\nLokasi yang diharapkan: web/src/App.tsx")
    src = APP.read_text(encoding='utf-8')
    css = CSS.read_text(encoding='utf-8')
    if MARKER in src:
        print("Mode preview sudah terpasang. Tidak ada perubahan.")
        print("Buka website: http://localhost:5173 (Vite) atau http://localhost (Docker).")
        return

    src = repl(src, "const initialDecisions: Decision[] = []", "const initialDecisions: Decision[] = []\n" + PREVIEW_SETUP, "deklarasi data awal")
    src = repl(src, "  const [token, setToken] = useState<string | null>(() => getStoredToken())\n  const [user, setUser] = useState<ApiUser | null>(null)",
               "  const [token, setToken] = useState<string | null>(() => getStoredToken())\n  const [isPreview, setIsPreview] = useState(() => PREVIEW_ENABLED && !getStoredToken())\n  const [user, setUser] = useState<ApiUser | null>(() => PREVIEW_ENABLED && !getStoredToken() ? previewUser : null)", "status login")
    src = repl(src, "  const [customerRows, setCustomerRows] = useState<Customer[]>(customers)\n  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null)",
               "  const [customerRows, setCustomerRows] = useState<Customer[]>(() => PREVIEW_ENABLED && !getStoredToken() ? previewCustomers : customers)\n  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(() => PREVIEW_ENABLED && !getStoredToken() ? previewCustomers[0] : null)", "data customer")
    src = repl(src, "  const [campaigns, setCampaigns] = useState(initialCampaigns)\n  const [reviews, setReviews] = useState(initialReviews)\n  const [decisions, setDecisions] = useState(initialDecisions)",
               "  const [campaigns, setCampaigns] = useState(() => PREVIEW_ENABLED && !getStoredToken() ? previewCampaigns : initialCampaigns)\n  const [reviews, setReviews] = useState(() => PREVIEW_ENABLED && !getStoredToken() ? previewReviews : initialReviews)\n  const [decisions, setDecisions] = useState(() => PREVIEW_ENABLED && !getStoredToken() ? previewDecisions : initialDecisions)", "kampanye dan review")
    src = repl(src, "({ drift: [], campaign_measurements: [], audit: [], pipeline_runs: [] })",
               "(PREVIEW_ENABLED && !getStoredToken() ? previewMonitoring : { drift: [], campaign_measurements: [], audit: [], pipeline_runs: [] })", "monitoring state")
    src = repl(src, "  async function handleLogin(email: string, password: string) {\n    const result = await api.login(email, password)\n    storeToken(result.access_token)\n    setToken(result.access_token)\n  }\n\n  function logout() {",
               "  async function handleLogin(email: string, password: string) {\n    const result = await api.login(email, password)\n    setIsPreview(false)\n    setUser(null)\n    storeToken(result.access_token)\n    setToken(result.access_token)\n  }\n\n  function enterPreview() {\n    storeToken(null)\n    setToken(null)\n    setIsPreview(true)\n    setUser(previewUser)\n    setCustomerRows(previewCustomers)\n    setSelectedCustomer(previewCustomers[0])\n    setCampaigns(previewCampaigns)\n    setReviews(previewReviews)\n    setDecisions(previewDecisions)\n    setMonitoringData(previewMonitoring)\n    setProvenance(null)\n    setApiError('')\n    setPage('dashboard')\n  }\n\n  function showLogin() {\n    setIsPreview(false)\n    setUser(null)\n    setApiError('')\n  }\n\n  function logout() {\n    if (PREVIEW_ENABLED) { enterPreview(); return }", "pergantian login/preview")
    src = repl(src, "  if (!token || !user) return <LoginScreen onLogin={handleLogin} error={apiError} />\n  const canManageCampaigns = user.roles.some", "  if ((!token && !isPreview) || !user) return <LoginScreen onLogin={handleLogin} error={apiError} onPreview={PREVIEW_ENABLED ? enterPreview : undefined} />\n  const canManageCampaigns = user.roles.some", "login gate")
    src = repl(src, "          <div className=\"persona-label\">ROLE AKTIF DARI SERVER</div>", "          <div className=\"persona-label\">{isPreview ? 'MODE PREVIEW — DATA SIMULASI' : 'ROLE AKTIF DARI SERVER'}</div>", "label role")
    src = repl(src, '<button className="plain-nav" onClick={logout}><LogOut size={17} /> Keluar</button>',
               '<button className="plain-nav" onClick={isPreview ? showLogin : logout}><LogOut size={17} /> {isPreview ? \'Login ke data asli\' : \'Keluar\'}</button>', "sidebar login")
    src = repl(src, "        {apiError && <div className=\"api-alert\"", "        {isPreview && <div className=\"preview-banner\" role=\"status\"><strong>MODE PREVIEW</strong><span>Data simulasi, bukan data pelanggan asli. Fitur penyimpanan dan akses API membutuhkan login.</span><button onClick={showLogin}>Login untuk data asli →</button></div>}\n        {apiError && <div className=\"api-alert\"", "banner preview")
    src = repl(src, "            <Dashboard \n              campaigns={campaigns}", "            <Dashboard \n              isPreview={isPreview}\n              campaigns={campaigns}", "props dashboard")
    src = repl(src, "<MonitoringPage token={token} data={monitoringData}", "<MonitoringPage token={token ?? ''} data={monitoringData}", "monitoring nullable token")
    src = repl(src,
        "function Dashboard({ campaigns, customers: customerRows, reviews, decisions, monitoring, onSeedCustomers, canSeed, canManageCampaigns, onOpenCustomers, onNewCampaign, onNavigate }: { campaigns: Campaign[];",
        "function Dashboard({ isPreview, campaigns, customers: customerRows, reviews, decisions, monitoring, onSeedCustomers, canSeed, canManageCampaigns, onOpenCustomers, onNewCampaign, onNavigate }: { isPreview: boolean; campaigns: Campaign[];",
        "tipe props dashboard")
    src = repl(src, 'change="API" detail="core.customers"', 'change={isPreview ? "Contoh" : "API"} detail={isPreview ? "Data simulasi" : "core.customers"}', "metric API")
    src = repl(src, 'change="Persisten" detail="dec.nba_decisions"', 'change={isPreview ? "Contoh" : "Persisten"} detail={isPreview ? "Data simulasi" : "dec.nba_decisions"}', "metric keputusan")
    src = repl(src, "      <ShieldCheck size={14} /> Keamanan & Compliance T-SEC-03: Channel Simulator aktif (Tanpa vendor email/SMS eksternal) <span>Append-only Audit Log Active</span>",
               "      <ShieldCheck size={14} /> {isPreview ? 'Preview saja — data fiktif, tidak ada aktivitas server' : 'Keamanan & Compliance T-SEC-03: Channel Simulator aktif (Tanpa vendor email/SMS eksternal)'} <span>{isPreview ? 'Login diperlukan untuk data asli' : 'Append-only Audit Log Active'}</span>", "catatan keamanan")
    src = repl(src, "function LoginScreen({ onLogin, error }: { onLogin: (email: string, password: string) => Promise<void>; error: string }) {",
               "function LoginScreen({ onLogin, error, onPreview }: { onLogin: (email: string, password: string) => Promise<void>; error: string; onPreview?: () => void }) {", "LoginScreen props")
    src = repl(src, "</button></form><div className=\"login-security\">", "</button></form>{onPreview && <button className=\"preview-return\" onClick={onPreview}>← Kembali ke dashboard preview</button>}<div className=\"login-security\">", "back to preview")
    # On expired tokens, fall back to preview instead of a blank login page.
    src = repl(src, "          storeToken(null)\n          setToken(null)\n          setUser(null)", "          if (PREVIEW_ENABLED) enterPreview()\n          else { storeToken(null); setToken(null); setUser(null) }", "expired auth")

    if MARKER not in css:
        css += '\n' + CSS_ADD
    time_tag = datetime.now().strftime('%Y%m%d_%H%M%S')
    bapp = APP.with_name(f'App.tsx.backup_{time_tag}')
    bcss = CSS.with_name(f'styles.css.backup_{time_tag}')
    shutil.copy2(APP, bapp)
    shutil.copy2(CSS, bcss)
    APP.write_text(src, encoding='utf-8')
    CSS.write_text(css, encoding='utf-8')
    print('BERHASIL: mode preview dashboard aktif (tanpa login).')
    print('Backup App.tsx:', bapp)
    print('Backup styles.css:', bcss)
    print('Frontend Vite: cd web ; npm run dev ; buka http://localhost:5173')
    print('Jika memakai Docker: docker compose up -d --build web ; buka http://localhost')
    print('Untuk mewajibkan login lagi, ubah PREVIEW_ENABLED = true menjadi false di web/src/App.tsx.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(f'ERROR: {exc}')
