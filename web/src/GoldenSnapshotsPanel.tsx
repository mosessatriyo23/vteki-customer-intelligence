import { useEffect, useState } from 'react'
import { api, type ApiGoldenCustomer } from './api'

const currency = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  maximumFractionDigits: 0,
})

export function GoldenSnapshotsPanel({ token, canReview }: { token: string | null; canReview: boolean }) {
  const [snapshots, setSnapshots] = useState<ApiGoldenCustomer[]>([])
  const [error, setError] = useState('')
  const [provenance, setProvenance] = useState<Record<string, unknown> | null>(null)
  const [selected, setSelected] = useState('')

  useEffect(() => {
    if (!token) return
    let active = true
    void api.goldenCustomers(token)
      .then((rows) => { if (active) setSnapshots(rows) })
      .catch((problem: unknown) => { if (active) setError(problem instanceof Error ? problem.message : 'Gagal memuat snapshot') })
    return () => { active = false }
  }, [token])

  async function showLineage(goldenId: string) {
    if (!token || !canReview) return
    setSelected(goldenId)
    setProvenance(null)
    try {
      const details = await api.goldenProvenance(token, goldenId)
      setProvenance(details)
      setError('')
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : 'Gagal memuat provenance')
    }
  }

  return <section className="panel" style={{ marginTop: 20, padding: 20 }} aria-label="Golden Customer snapshots">
    <h2>Golden Customer — Snapshot PostgreSQL</h2>
    <p>Data historis hasil identity resolution dan Customer 360; status PROVISIONAL bukan identitas yang sudah disetujui. Tidak memakai data demo core.customers.</p>
    {!token && <p>Login diperlukan untuk melihat snapshot asli.</p>}
    {error && <p role="alert">{error}</p>}
    {token && !error && snapshots.length === 0 && <p>Belum ada snapshot terpublikasi. Jalankan pipeline serving setelah ingestion dan identity registry siap.</p>}
    {snapshots.length > 0 && <div style={{ overflowX: 'auto' }}><table className="customer-table">
      <thead><tr><th>Golden ID</th><th>Cutoff</th><th>Retained revenue (IDR)</th><th>Lifecycle</th><th>Status identitas</th><th>Provenance</th></tr></thead>
      <tbody>{snapshots.map((row) => <tr key={row.golden_customer_id}>
        <td>{row.golden_customer_id}</td>
        <td>{new Date(row.cutoff_at).toLocaleDateString('id-ID')}</td>
        <td>{currency.format(row.retained_revenue)}</td>
        <td>{row.lifecycle ?? 'Belum tersedia'}</td>
        <td>{row.identity_status}</td>
        <td>{canReview ? <button className="button button-secondary" type="button" onClick={() => void showLineage(row.golden_customer_id)}>Lihat</button> : 'Akses terbatas'}</td>
      </tr>)}</tbody>
    </table></div>}
    {selected && provenance && <div aria-live="polite" style={{ marginTop: 16 }}>
      <h3>Provenance: {selected}</h3>
      <p>Registry version: {String((provenance.snapshot as ApiGoldenCustomer | undefined)?.identity_registry_version ?? '—')}</p>
      <p>Source batch: {String((provenance.snapshot as ApiGoldenCustomer | undefined)?.source_batch_id ?? '—')}</p>
      <p>Source mappings: {Array.isArray(provenance.mapping) ? provenance.mapping.length : 0}</p>
      <p>Review audit entries: {Array.isArray(provenance.review_audit) ? provenance.review_audit.length : 0}</p>
    </div>}
  </section>
}
