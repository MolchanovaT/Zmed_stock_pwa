import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { listReports } from '../api/clinic_reports'

const STATUS_LABEL = {
  draft: { text: 'Черновик', cls: 'bg-amber-100 text-amber-800' },
  submitted: { text: 'Отправлен', cls: 'bg-emerald-100 text-emerald-800' },
}

export default function ClinicReportsPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()
  const [reports, setReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [filterStatus, setFilterStatus] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [error, setError] = useState('')

  const refresh = () => {
    setLoading(true)
    const params = {}
    if (filterStatus) params.status = filterStatus
    if (dateFrom) params.date_from = dateFrom
    if (dateTo) params.date_to = dateTo
    listReports(params)
      .then((r) => { setReports(r); setError('') })
      .catch((e) => setError(e.response?.data?.detail || 'Ошибка загрузки'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

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
          <Link to="/clinic-reports/new"
                className="bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
            + Новый отчёт
          </Link>
        </div>

        <div className="bg-white rounded-xl border p-3 flex flex-wrap gap-3 items-end mb-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Статус</label>
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
                    className="border rounded px-2 py-1 text-sm">
              <option value="">все</option>
              <option value="draft">Черновик</option>
              <option value="submitted">Отправлен</option>
            </select>
          </div>
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
          <button onClick={refresh}
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
            {reports.map((r) => {
              const st = STATUS_LABEL[r.status] || { text: r.status, cls: 'bg-gray-100 text-gray-600' }
              const implants = Array.isArray(r.implants_used) ? r.implants_used : []
              return (
                <Link key={r.id} to={`/clinic-reports/${r.id}`}
                      className="block bg-white rounded-xl border hover:border-brand-300 hover:shadow p-4 transition">
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
                </Link>
              )
            })}
          </div>
        )}
      </main>
    </div>
  )
}
