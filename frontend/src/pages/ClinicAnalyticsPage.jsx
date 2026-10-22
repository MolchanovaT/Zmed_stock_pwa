import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie,
  PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { useAuth } from '../store/auth'
import {
  getByClinic, getMonthly, getTopOperationTypes,
} from '../api/clinic_analytics'

// Палитра — brand-neutral, без завязок на конкретную тему
const COLORS = ['#9a2a3a', '#2c5f8a', '#4b8c6b', '#c89b4a', '#6a5acd',
                 '#d87b3b', '#4a7a8c', '#8b6f47', '#7a5b8a', '#5a7a4a']

export default function ClinicAnalyticsPage() {
  const navigate = useNavigate()
  const { user, signout } = useAuth()

  const [monthly, setMonthly] = useState([])
  const [byClinic, setByClinic] = useState([])
  const [topTypes, setTopTypes] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      getMonthly(12),
      getByClinic(),
      getTopOperationTypes({ limit: 8 }),
    ])
      .then(([m, c, t]) => { setMonthly(m); setByClinic(c); setTopTypes(t); setError('') })
      .catch((e) => setError(e.response?.data?.detail || 'Ошибка загрузки'))
      .finally(() => setLoading(false))
  }, [])

  // Сводка — верхние KPI
  const kpi = {
    reports: monthly.reduce((s, m) => s + m.reports, 0),
    implants: monthly.reduce((s, m) => s + m.implants_total, 0),
    losses: monthly.reduce((s, m) => s + Math.max(0, m.losses_qty), 0),
    clinics: byClinic.length,
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/home')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← Разделы</button>
          <span className="text-xl ml-3">📊</span>
          <span className="font-bold text-gray-800">Аналитика клиник</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={signout}
                  className="text-sm text-gray-400 hover:text-red-500">Выйти</button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-5">
        {error && <div className="bg-red-50 text-red-700 rounded p-3 text-sm">{error}</div>}

        {/* KPI */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi label="Отчёты (12 мес)" value={kpi.reports} color="text-brand-600"/>
          <Kpi label="Имплантов использовано" value={kpi.implants} color="text-sky-600"/>
          <Kpi label="Потерь, шт" value={kpi.losses} color="text-rose-600"/>
          <Kpi label="Активные клиники" value={kpi.clinics} color="text-emerald-600"/>
        </div>

        {loading ? (
          <div className="text-center text-gray-400 py-16">Загрузка…</div>
        ) : (
          <>
            {/* Линейный график: по месяцам */}
            <Card title="По месяцам">
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={monthly}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eee"/>
                  <XAxis dataKey="month" fontSize={12}/>
                  <YAxis fontSize={12}/>
                  <Tooltip/>
                  <Legend/>
                  <Line type="monotone" dataKey="reports"
                        name="Отчёты" stroke="#9a2a3a" strokeWidth={2}/>
                  <Line type="monotone" dataKey="implants_total"
                        name="Импланты (шт)" stroke="#2c5f8a" strokeWidth={2}/>
                  <Line type="monotone" dataKey="losses_qty"
                        name="Потери (шт)" stroke="#c89b4a" strokeWidth={2}/>
                </LineChart>
              </ResponsiveContainer>
            </Card>

            {/* По клиникам: bar */}
            <Card title="По клиникам (отчёты и импланты)">
              {byClinic.length === 0 ? (
                <p className="text-gray-400 text-sm">Нет данных</p>
              ) : (
                <ResponsiveContainer width="100%" height={Math.max(260, byClinic.length * 36)}>
                  <BarChart layout="vertical" data={byClinic} margin={{ left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eee"/>
                    <XAxis type="number" fontSize={12}/>
                    <YAxis type="category" dataKey="name" width={160} fontSize={12}/>
                    <Tooltip/>
                    <Legend/>
                    <Bar dataKey="reports"  name="Отчёты"       fill="#9a2a3a"/>
                    <Bar dataKey="implants_total" name="Импланты" fill="#2c5f8a"/>
                    <Bar dataKey="losses_qty" name="Потери (шт)" fill="#c89b4a"/>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </Card>

            {/* Pie: топ-операции */}
            <Card title="Топ типов операций">
              {topTypes.length === 0 ? (
                <p className="text-gray-400 text-sm">Нет данных</p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <PieChart>
                    <Pie
                      data={topTypes}
                      dataKey="count"
                      nameKey="operation_type"
                      outerRadius={120}
                      label={(e) => `${e.operation_type} (${e.count})`}
                      fontSize={11}
                    >
                      {topTypes.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]}/>
                      ))}
                    </Pie>
                    <Tooltip/>
                  </PieChart>
                </ResponsiveContainer>
              )}
            </Card>
          </>
        )}
      </main>
    </div>
  )
}

function Kpi({ label, value, color }) {
  return (
    <div className="bg-white rounded-xl border p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
    </div>
  )
}

function Card({ title, children }) {
  return (
    <div className="bg-white rounded-xl border p-4">
      <h3 className="font-semibold text-gray-800 mb-3">{title}</h3>
      {children}
    </div>
  )
}
