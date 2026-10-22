import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import {
  listLosses, listOrganizationsForLosses, downloadLossesXlsx,
} from '../api/clinic_stock'

const KIND_LABEL = { write_off: 'Списание', inventory_adjust: 'Инвентаризация' }
const KIND_COLOR = {
  write_off: 'bg-red-100 text-red-800',
  inventory_adjust: 'bg-purple-100 text-purple-800',
}

export default function ClinicLossesPage() {
  const navigate = useNavigate()
  const { user, signout } = useAuth()

  const [movs, setMovs] = useState([])
  const [orgs, setOrgs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filters, setFilters] = useState({
    organization_id: '',
    date_from: '',
    date_to: '',
  })

  const paramsForApi = useMemo(() => {
    const p = {}
    if (filters.organization_id) p.organization_id = filters.organization_id
    if (filters.date_from) p.date_from = filters.date_from
    if (filters.date_to)   p.date_to = filters.date_to
    return p
  }, [filters])

  const refresh = async () => {
    setLoading(true); setError('')
    try {
      const data = await listLosses(paramsForApi)
      setMovs(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    listOrganizationsForLosses().then(setOrgs).catch(() => {})
    refresh()  // eslint-disable-next-line
  }, [])

  const totals = useMemo(() => {
    let writeOff = 0, inventoryMinus = 0, inventoryPlus = 0
    for (const m of movs) {
      if (m.kind === 'write_off') writeOff += m.quantity
      else if (m.kind === 'inventory_adjust') {
        if (m.quantity < 0) inventoryMinus += -m.quantity
        else inventoryPlus += m.quantity
      }
    }
    return { writeOff, inventoryMinus, inventoryPlus,
             total: writeOff + inventoryMinus - inventoryPlus }
  }, [movs])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/clinic-stock')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← К учёту</button>
          <span className="text-xl ml-3">🚨</span>
          <span className="font-bold text-gray-800">Потери на ОХ</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={signout}
                  className="text-sm text-gray-400 hover:text-red-500">Выйти</button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-5">
        {/* Фильтры */}
        <div className="bg-white rounded-xl border p-4 flex flex-wrap gap-3 items-end">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Клиника</label>
            <select value={filters.organization_id}
                    onChange={(e) => setFilters({ ...filters, organization_id: e.target.value })}
                    className="border rounded px-3 py-2 text-sm min-w-[200px]">
              <option value="">— все —</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id}>{o.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">С</label>
            <input type="date" value={filters.date_from}
                   onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
                   className="border rounded px-3 py-2 text-sm"/>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">По</label>
            <input type="date" value={filters.date_to}
                   onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
                   className="border rounded px-3 py-2 text-sm"/>
          </div>
          <button onClick={refresh}
                  className="bg-gray-800 text-white rounded px-4 py-2 text-sm">Применить</button>
          <button onClick={() => downloadLossesXlsx(paramsForApi)}
                  className="bg-emerald-600 text-white rounded px-4 py-2 text-sm">
            📥 XLSX
          </button>
        </div>

        {/* Сводка */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="bg-white rounded-xl border p-3">
            <div className="text-xs text-gray-500">Списано</div>
            <div className="text-xl font-bold text-red-600">{totals.writeOff}</div>
          </div>
          <div className="bg-white rounded-xl border p-3">
            <div className="text-xs text-gray-500">Недостача по инвент.</div>
            <div className="text-xl font-bold text-purple-600">{totals.inventoryMinus}</div>
          </div>
          <div className="bg-white rounded-xl border p-3">
            <div className="text-xs text-gray-500">Излишки (нашли)</div>
            <div className="text-xl font-bold text-emerald-600">+{totals.inventoryPlus}</div>
          </div>
          <div className="bg-white rounded-xl border p-3">
            <div className="text-xs text-gray-500">Чистые потери</div>
            <div className="text-xl font-bold text-gray-800">{totals.total}</div>
          </div>
        </div>

        {error && <div className="bg-red-50 text-red-700 rounded p-3 text-sm">{error}</div>}

        {/* Таблица */}
        <div className="bg-white rounded-xl border overflow-x-auto">
          {loading ? <div className="text-center text-gray-400 py-10">Загрузка…</div>
           : movs.length === 0 ? (
            <div className="text-center text-gray-400 py-10">Потерь не найдено</div>
           ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500">
                <tr>
                  <th className="text-left p-2">Когда</th>
                  <th className="text-left p-2">Клиника</th>
                  <th className="text-left p-2">Тип</th>
                  <th className="text-left p-2">Партия</th>
                  <th className="text-left p-2">Lot / Срок</th>
                  <th className="text-right p-2">Кол-во</th>
                  <th className="text-left p-2">Отчёт</th>
                  <th className="text-left p-2">Заметка</th>
                </tr>
              </thead>
              <tbody>
                {movs.map((m) => (
                  <tr key={m.id} className="border-t">
                    <td className="p-2 text-xs text-gray-500">
                      {m.created_at ? new Date(m.created_at).toLocaleString() : ''}
                    </td>
                    <td className="p-2">{m.organization_name}</td>
                    <td className="p-2">
                      <span className={`${KIND_COLOR[m.kind]} text-xs px-2 py-0.5 rounded-full font-medium`}>
                        {KIND_LABEL[m.kind] || m.kind}
                      </span>
                    </td>
                    <td className="p-2">
                      <div className="font-medium">{m.item.article}</div>
                      <div className="text-xs text-gray-500">{m.item.nomenclature}</div>
                    </td>
                    <td className="p-2 text-xs text-gray-500">
                      {m.item.lot_number || '—'}<br/>
                      {m.item.expiration_date || '—'}
                    </td>
                    <td className={`p-2 text-right font-semibold ${
                      m.quantity < 0 ? 'text-red-600' :
                      m.kind === 'inventory_adjust' && m.quantity > 0 ? 'text-emerald-600' :
                      'text-gray-800'
                    }`}>
                      {m.quantity > 0 ? '+' : ''}{m.quantity}
                    </td>
                    <td className="p-2 text-xs">
                      {m.operation_report_id
                        ? <a href={`/clinic-reports/${m.operation_report_id}`}
                             className="text-brand-600 hover:underline">
                            #{m.operation_report_id}
                          </a>
                        : <span className="text-gray-300">—</span>}
                    </td>
                    <td className="p-2 text-xs text-gray-500 max-w-xs truncate">{m.note || ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
           )}
        </div>
      </main>
    </div>
  )
}
