// ui_score_status_check.mjs — uji teks status skor di UI terhadap kondisi nyata backend.
//
// Membaca web/src/App.tsx (TIDAK mengubahnya), mengambil `scoreAvailabilityLabel` dan
// `scoreServingStatus`, lalu menjalankannya untuk 11 kondisi yang dihasilkan backend
// (lihat uat_dry_run.py dan docs/christ_business/integration/UI_SCORE_STATES_SPEC.md §8).
//
// Jalankan dari root repo (Node 22.13 ke atas):
//   node docs/christ_business/demo/ui_score_status_check.mjs [web/src/App.tsx] [label]
// Keluar dengan kode 1 bila ada kondisi yang teksnya tidak sesuai.
import fs from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
const file = process.argv[2] || 'web/src/App.tsx'
const label = process.argv[3] || 'App.tsx'
const src = fs.readFileSync(file, 'utf8')
const start = src.indexOf('function scoreAvailabilityLabel')
const end = src.indexOf('function formatMeasurementValue')
if (start < 0 || end < 0) throw new Error('fungsi tidak ditemukan')
const js = stripTypeScriptTypes(src.slice(start, end))
const { scoreServingStatus } = new Function(js + '\nreturn { scoreServingStatus }')()

// Kondisi nyata dari backend (hasil uat_dry_run.py): [nama, servingReady, modelReviewStatus, scoreUnavailableReason, harapan]
const cases = [
  ['1 Skor belum ada',                         false, null,             'SCORE_ROW_MISSING',          /belum tersedia/i],
  ['2 Run menunggu review',                    false, 'pending_review', 'MODEL_RUN_NOT_REVIEWED',     /menunggu pemeriksaan/i],
  ['3 Run ditolak',                            false, 'rejected',       'MODEL_RUN_NOT_REVIEWED',     /ditolak/i],
  ['4 Sudah direview, belum diizinkan',        false, 'reviewed',       'MODEL_USAGE_NOT_APPROVED',   /belum disetujui/i],
  ['5 Kontrak belum lengkap + pending_review', false, 'pending_review', 'SCORE_CONTRACT_NOT_SERVING', /kontrak|format|belum lengkap/i],
  ['6 Kontrak belum lengkap + reviewed',       false, 'reviewed',       'SCORE_CONTRACT_NOT_SERVING', /kontrak|format|belum lengkap/i],
  ['7 Skor KEDALUWARSA',                       false, 'reviewed',       'SCORE_EXPIRED',              /kedaluwarsa/i],
  ['8 Skor milik ID lain',                     false, 'reviewed',       'SCORE_CUSTOMER_MISMATCH',    /identitas|tidak cocok/i],
  ['9 Field skor tidak lengkap',               false, 'reviewed',       'SCORE_FIELDS_INCOMPLETE',    /belum lengkap/i],
  ['10 Skor siap, sumber lain belum lengkap',  false, 'reviewed',       null,                         /sumber.*belum lengkap/i],
  ['11 Skor siap dan keputusan siap',          true,  'reviewed',       null,                         /siap dipakai/i],
]
let fail = 0
console.log(`UI: ${label}`)
for (const [name, ready, review, reason, expect] of cases) {
  const text = scoreServingStatus({ servingReady: ready, modelReviewStatus: review, scoreUnavailableReason: reason })
  const ok = expect.test(text)
  if (!ok) fail++
  console.log(`${ok ? 'OK  ' : 'GAGAL'} | ${name.padEnd(42)} | "${text}"`)
}
console.log(`\n${cases.length - fail}/${cases.length} sesuai harapan`)
process.exit(fail ? 1 : 0)
