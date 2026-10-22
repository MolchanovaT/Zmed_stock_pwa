import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import {
  listReports, downloadReportsXlsx, downloadReportsPdfZip, listTags, bulkTag,
} from '../api/clinic_reports'

const STATUS_LABEL = {
  draft: { text: 'Черновик', cls: 'bg-amber-100 text-amber-800' },
  submitted: { text: 'Отправлен', cls: 'bg-emerald-100 text-emerald-800' },
}

export default function ClinicReportsPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()
  const [reports, setReports] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterTagId, setFilterTagId] = useState('')
  const [availableTags, setAvailableTags] = useState([])
  const [searchQ, setSearchQ] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(new Set())
  const [bulkTagId, setBulkTagId] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const PAGE_SIZE = 50

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const toggleSelectAll = (visible) => {
    setSelected((prev) => {
      const next = new Set(prev)
      const allPresent = visible.every((r) => next.has(r.id))
      if (allPresent) visible.forEach((r) => next.delete(r.id))
      else visible.forEach((r) => next.add(r.id))
      return next
    })
  }

  const runBulkTag = async (mode) => {
    if (!bulkTagId || selected.size === 0) return
    setBulkBusy(true)
    try {
      await bulkTag([...selected], Number(bulkTagId), mode)
      setSelected(new Set())
      refresh(false)
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка группового действия')
    } finally {
      setBulkBusy(false)
    }
  }

  const refresh = (append = false) => {
    setLoading(true)
    const nextOffset = append ? offset + PAGE_SIZE : 0
    const params = { limit: PAGE_SIZE, offset: nextOffset }
    if (filterStatus) params.status = filterStatus
    if (filterTagId) params.tag_id = filterTagId
    if (searchQ.trim()) params.q = searchQ.trim()
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    listReports(params)
      .then((r) => {
        setReports((prev) => append ? [...prev, ...(r.reports || [])] : (r.reports || []))
        setTotal(r.total || 0)
        setOffset(nextOffset)
        setError('')
      })
      .catch((e) => setError(e.response?.data?.detail || 'Ошибка загрузки'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh(false)
    listTags().then(setAvailableTags).catch(() => {})
    /* eslint-disable-next-line */
  }, [])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/home')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← Разделы</button>
          <span className="text-xl ml-3">📋</span>
          <span className="font-bold text-gray-800">Отчёты об операциях</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={signout}
                  className="text-sm text-gray-400 hover:text-red-500">Выйти</button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
          <h1 className="text-xl font-bold text-gray-800">Отчёты</h1>
          <div className="flex gap-2 flex-wrap">
            <Link to="/clinic-analytics"
                  className="bg-sky-600 hover:bg-sky-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              📊 Аналитика
            </Link>
            <button
              onClick={() => {
                const params = {}
                if (filterStatus) params.status = filterStatus
                if (filterTagId) params.tag_id = filterTagId
                if (dateFrom) params.date_from = dateFrom
                if (dateTo) params.date_to = dateTo
                downloadReportsXlsx(params)
              }}
              className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-medium"
            >
              📥 XLSX
            </button>
            <button
              onClick={() => {
                const params = {}
                if (filterTagId) params.tag_id = filterTagId
                if (dateFrom) params.date_from = dateFrom
                if (dateTo) params.date_to = dateTo
                // Статус: всегда submitted для архива PDF
                downloadReportsPdfZip(params)
              }}
              title="ZIP с PDF каждого отправленного отчёта (до 100 за раз)"
              className="bg-amber-600 hover:bg-amber-700 text-white rounded-lg px-4 py-2 text-sm font-medium"
            >
              📦 PDF ZIP
            </button>
            <Link to="/clinic-reports/new"
                  className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              + Новый отчёт
            </Link>
          </div>
        </div>

        <div className="bg-white rounded-xl border p-3 flex flex-wrap gap-3 items-end mb-4">
          <div className="flex-1 min-w-[200px]">
            <label className="block text-xs text-gray-500 mb-1">Поиск</label>
            <input value={searchQ}
                   onChange={(e) => setSearchQ(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && refresh(false)}
                   placeholder="По коду, врачу, диагнозу, заметке"
                   className="w-full border rounded px-2 py-1 text-sm"/>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Статус</label>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
                    className="border rounded px-2 py-1 text-sm">
              <option value="">все</option>
              <option value="draft">Черновик</option>
              <option value="submitted">Отправлен</option>
            </select>
          </div>
          {availableTags.length > 0 && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Тег</label>
              <select value={filterTagId} onChange={(e) => setFilterTagId(e.target.value)}
                      className="border rounded px-2 py-1 text-sm">
                <option value="">все</option>
                {availableTags.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="block text-xs text-gray-500 mb-1">С</label>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
                   className="border rounded px-2 py-1 text-sm"/>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">По</label>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
                   className="border rounded px-2 py-1 text-sm"/>
          </div>
          <button onClick={() => refresh(false)}
                  className="bg-gray-800 text-white rounded px-3 py-1 text-sm">Применить</button>
        </div>

        {error && <div className="bg-red-50 text-red-700 rounded p-3 mb-3 text-sm">{error}</div>}

        {loading ? (
          <div className="text-center text-gray-400 py-16">Загрузка…</div>
        ) : reports.length === 0 ? (
          <div className="text-center text-gray-400 py-16">
            <div className="text-5xl mb-3">📭</div>
            <p>Отчётов пока нет</p>
          </div>
        ) : (
          <div className="space-y-3">
            {reports.length > 0 && availableTags.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap text-xs text-gray-500 px-1">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox"
                         checked={reports.length > 0 && reports.every((r) => selected.has(r.id))}
                         onChange={() => toggleSelectAll(reports)}/>
                  Выбрать все на странице
                </label>
                {selected.size > 0 && (
                  <span className="ml-2 text-gray-700">
                    выбрано: {selected.size}
                  </span>
                )}
              </div>
            )}
            {reports.map((r) => {
              const st = STATUS_LABEL[r.status] || { text: r.status, cls: 'bg-gray-100 text-gray-600' }
              const implants = Array.isArray(r.implants_used) ? r.implants_used : []
              return (
                <div key={r.id}
                     className="flex items-stretch gap-2 bg-white rounded-xl border hover:border-brand-300 hover:shadow transition">
                  {availableTags.length > 0 && (
                    <label className="flex items-center pl-3 cursor-pointer"
                           onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox"
                             checked={selected.has(r.id)}
                             onChange={() => toggleSelect(r.id)}/>
                    </label>
                  )}
                  <Link to={`/clinic-reports/${r.id}`}
                        className="flex-1 block p-4">
                  <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                    <div className="font-semibold text-gray-800">
                      #{r.id} · {r.operation_date} · {r.operation_type}
                    </div>
                    <span className={`${st.cls} text-xs px-2 py-0.5 rounded-full font-medium`}>
                      {st.text}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600 flex gap-4 flex-wrap">
                    <span>👨‍⚕️ {r.doctor_name}</span>
                    <span>🧾 {r.patient_code}</span>
                    {r.department && <span>🏥 {r.department}</span>}
                    <span>🔩 {implants.length} поз.</span>
                    {r.files?.length > 0 && <span>📎 {r.files.length} файл(ов)</span>}
                  </div>
                  {r.tags?.length > 0 && (
                    <div className="flex gap-1 flex-wrap mt-2">
                      {r.tags.map((t) => (
                        <span key={t.id}
                              style={{ background: t.color, color: '#fff' }}
                              className="text-xs px-2 py-0.5 rounded-full font-medium">
                          {t.name}
                        </span>
                      ))}
                    </div>
                  )}
                  </Link>
                </div>
              )
            })}
          </div>
        )}

        {!loading && reports.length > 0 && (
          <div className="mt-4 flex items-center justify-between gap-2 flex-wrap">
            <span className="text-xs text-gray-400">
              показано {reports.length} из {total}
            </span>
            {reports.length < total && (
              <button onClick={() => refresh(true)} disabled={loading}
                      className="bg-white border border-brand-500 text-brand-600 hover:bg-brand-50 rounded-lg px-5 py-2 text-sm font-medium disabled:opacity-50">
                Загрузить ещё ({total - reports.length})
              </button>
            )}
          </div>
        )}
      </main>

      {/* Плавающая панель группового действия */}
      {selected.size > 0 && availableTags.length > 0 && (
        <div className="fixed bottom-4 inset-x-4 md:left-auto md:right-6 md:w-96 z-30">
          <div className="bg-white border rounded-xl shadow-lg p-3 space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium text-gray-800">
                Выбрано: {selected.size}
              </span>
              <button onClick={() => setSelected(new Set())}
                      className="text-xs text-gray-500 hover:text-gray-800">
                Снять выбор
              </button>
            </div>
            <select value={bulkTagId}
                    onChange={(e) => setBulkTagId(e.target.value)}
                    className="w-full border rounded px-2 py-1 text-sm">
              <option value="">— выберите тег —</option>
              {availableTags.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <button onClick={() => runBulkTag('add')}
                      disabled={!bulkTagId || bulkBusy}
                      className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded px-3 py-1.5 text-sm disabled:opacity-50">
                + Добавить тег
              </button>
              <button onClick={() => runBulkTag('remove')}
                      disabled={!bulkTagId || bulkBusy}
                      className="flex-1 bg-rose-600 hover:bg-rose-700 text-white rounded px-3 py-1.5 text-sm disabled:opacity-50">
                − Снять тег
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
