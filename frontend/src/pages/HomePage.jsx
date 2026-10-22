import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { getOrders } from '../api/cart'
import { listReports, listTags } from '../api/clinic_reports'
import { getMyActivity, getByClinic } from '../api/clinic_analytics'
import OrderCard from '../components/OrderCard'

const HEALTH_META = {
  ok:       { label: 'активна', cls: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
  warning:  { label: '15-30 дн', cls: 'bg-amber-100 text-amber-800 border-amber-200' },
  silent:   { label: '>30 дн / молчит', cls: 'bg-rose-100 text-rose-800 border-rose-200' },
  no_data:  { label: 'нет данных', cls: 'bg-gray-100 text-gray-500 border-gray-200' },
}

/* ── SVG-иконки модулей ─────────────────────────────────────────────────── */

function IconSpine() {
  return (
    <svg viewBox="0 0 40 56" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      {/* Позвонки: 5 штук, равномерно по высоте */}
      {[4, 14, 24, 34, 44].map((y, i) => (
        <g key={i}>
          {/* Тело позвонка */}
          <rect x="11" y={y} width="18" height="7" rx="2" strokeWidth="2" />
          {/* Левый отросток */}
          <line x1="11" y1={y + 3.5} x2="5" y2={y + 3.5} strokeWidth="2" />
          <line x1="5" y1={y + 1.5} x2="5" y2={y + 5.5} strokeWidth="1.5" />
          {/* Правый отросток */}
          <line x1="29" y1={y + 3.5} x2="35" y2={y + 3.5} strokeWidth="2" />
          <line x1="35" y1={y + 1.5} x2="35" y2={y + 5.5} strokeWidth="1.5" />
        </g>
      ))}
      {/* Межпозвонковые диски — тонкие линии между позвонками */}
      {[11, 21, 31, 41].map((y, i) => (
        <line key={i} x1="13" y1={y} x2="27" y2={y} strokeWidth="1" strokeDasharray="2 2" />
      ))}
    </svg>
  )
}

function IconJoint() {
  return (
    <svg viewBox="0 0 44 52" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      {/* Верхняя кость (бедренная) */}
      <path d="M22 4 C22 4 18 8 16 12 C14 16 15 20 17 22 C19 24 22 24 22 24"
            strokeWidth="2.5" />
      <path d="M22 4 C22 4 26 8 28 12 C30 16 29 20 27 22 C25 24 22 24 22 24"
            strokeWidth="2.5" />
      {/* Суставная щель */}
      <line x1="13" y1="26" x2="31" y2="26" strokeWidth="1" strokeDasharray="3 2" />
      {/* Нижняя кость (большеберцовая) */}
      <path d="M15 28 C13 30 13 34 15 36 L20 38 L20 48"
            strokeWidth="2.5" />
      <path d="M29 28 C31 30 31 34 29 36 L24 38 L24 48"
            strokeWidth="2.5" />
      <line x1="20" y1="48" x2="24" y2="48" strokeWidth="2.5" />
      {/* Суставная головка */}
      <path d="M16 24 Q22 20 28 24" strokeWidth="2" fill="none" />
      <path d="M15 28 Q22 32 29 28" strokeWidth="2" fill="none" />
    </svg>
  )
}

function IconTools() {
  return (
    <svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      {/* Скальпель */}
      <path d="M8 36 L28 10 L34 12 L32 18 Z" strokeWidth="2" />
      <line x1="8" y1="36" x2="14" y2="30" strokeWidth="2" />
      {/* Зажим/пинцет */}
      <line x1="26" y1="26" x2="36" y2="36" strokeWidth="2.5" />
      <line x1="30" y1="22" x2="38" y2="32" strokeWidth="2.5" />
      <path d="M26 26 Q28 24 30 22" strokeWidth="2" />
      <path d="M36 36 Q37 38 38 38 Q39 38 38 37" strokeWidth="1.5" />
    </svg>
  )
}

function IconReport() {
  return (
    <svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      {/* Планшет-отчёт */}
      <rect x="10" y="6" width="24" height="32" rx="2" strokeWidth="2.5"/>
      <rect x="16" y="4" width="12" height="6" rx="1" strokeWidth="2"/>
      {/* Строки */}
      <line x1="15" y1="18" x2="29" y2="18" strokeWidth="2"/>
      <line x1="15" y1="24" x2="29" y2="24" strokeWidth="2"/>
      <line x1="15" y1="30" x2="24" y2="30" strokeWidth="2"/>
      {/* Галочка */}
      <path d="M13 14 L15 16 L19 12" strokeWidth="2"/>
    </svg>
  )
}

function IconBox() {
  return (
    <svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      {/* Коробка */}
      <path d="M6 14 L22 6 L38 14 L38 32 L22 40 L6 32 Z" strokeWidth="2.5"/>
      <path d="M6 14 L22 22 L38 14" strokeWidth="2.5"/>
      <line x1="22" y1="22" x2="22" y2="40" strokeWidth="2.5"/>
      {/* Штрихкод-намёк */}
      <line x1="12" y1="26" x2="12" y2="34" strokeWidth="1.5"/>
      <line x1="15" y1="26" x2="15" y2="34" strokeWidth="1.5"/>
      <line x1="18" y1="26" x2="18" y2="34" strokeWidth="1.5"/>
    </svg>
  )
}

function IconSearch() {
  return (
    <svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg"
         className="w-8 h-8" stroke="white" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="19" cy="19" r="11" strokeWidth="2.5" />
      <line x1="27" y1="27" x2="38" y2="38" strokeWidth="2.5" />
      {/* ИНН внутри лупы */}
      <line x1="14" y1="15" x2="14" y2="23" strokeWidth="2" />
      <line x1="19" y1="15" x2="17" y2="19" strokeWidth="2" />
      <line x1="19" y1="15" x2="21" y2="19" strokeWidth="2" />
      <line x1="17" y1="19" x2="21" y2="19" strokeWidth="1.5" />
      <line x1="17" y1="19" x2="19" y2="23" strokeWidth="2" />
      <line x1="21" y1="19" x2="19" y2="23" strokeWidth="2" />
      <line x1="23" y1="15" x2="23" y2="23" strokeWidth="2" />
    </svg>
  )
}

/* ── Данные модулей ─────────────────────────────────────────────────────── */

const ALL_MODULES = [
  {
    id: 'implants',
    title: 'Импланты',
    description: 'Поиск остатков имплантов, корзина и оформление заказов',
    Icon: IconSpine,
    path: '/',
    color: 'from-brand-500 to-brand-600',
  },
  {
    id: 'implants_view',
    title: 'Импланты — просмотр',
    description: 'Поиск и просмотр остатков имплантов, экспорт в PDF',
    Icon: IconJoint,
    path: '/implants-view',
    color: 'from-indigo-500 to-indigo-600',
  },
  {
    id: 'supplies',
    title: 'Расходники и инструменты',
    description: 'Поиск остатков расходных материалов и инструментов',
    Icon: IconTools,
    path: '/supplies',
    color: 'from-teal-500 to-teal-600',
  },
  {
    id: 'inn_check',
    title: 'Проверка контрагентов',
    description: 'Проверка отгрузки по ИНН дилера или ЛПУ',
    Icon: IconSearch,
    path: '/inn-check',
    color: 'from-violet-500 to-violet-600',
  },
  {
    id: 'clinic_reports',
    title: 'Отчёты об операциях',
    description: 'Регистрация прошедших операций с фото/сканами отчётов',
    Icon: IconReport,
    path: '/clinic-reports',
    color: 'from-rose-500 to-rose-600',
  },
  {
    id: 'clinic_stock',
    title: 'Учёт на ОХ',
    description: 'Приход, расход и остатки имплантов на ответственном хранении',
    Icon: IconBox,
    path: '/clinic-stock',
    color: 'from-amber-500 to-amber-600',
  },
]

/* ── Страница ────────────────────────────────────────────────────────────── */

export default function HomePage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const availableModules = ALL_MODULES.filter(
    (m) => user?.modules?.includes(m.id)
  )

  const hasImplants = user?.modules?.includes('implants')
  const hasSupplies = user?.modules?.includes('supplies')
  const hasReports  = user?.modules?.includes('clinic_reports')
  const canSeeOrders = hasImplants || hasSupplies

  const [orders, setOrders] = useState([])
  const [reports, setReports] = useState([])
  const [myActivity, setMyActivity] = useState(null)
  const [clinicsHealth, setClinicsHealth] = useState([])
  const [reviewCount, setReviewCount] = useState(0)   // F38

  useEffect(() => {
    if (!canSeeOrders) return
    getOrders()
      .then((data) => setOrders(Array.isArray(data) ? data : []))
      .catch(() => {})
  }, [canSeeOrders])

  useEffect(() => {
    if (!hasReports) return
    listReports({ limit: 5 })
      .then((data) => setReports(data?.reports || []))
      .catch(() => {})
    getMyActivity().then(setMyActivity).catch(() => {})
    // F40 — цветовая карта клиник. Пытаемся — если юзер не ZMed, бэкенд
    // отдаст одну клинику (это ок).
    getByClinic().then(setClinicsHealth).catch(() => {})
    // F38 — счётчик «Требует разбора»
    listTags().then(async (tags) => {
      const t = tags.find((x) => x.name === 'Требует разбора')
      if (!t) return
      try {
        const resp = await listReports({ tag_id: t.id, limit: 1 })
        setReviewCount(resp?.total || 0)
      } catch { /* ignore */ }
    }).catch(() => {})
  }, [hasReports])

  const recentOrders = orders.slice(0, 5)
  const recentReports = reports.slice(0, 5)
  // Показываем grid только если клиник больше одной (у клиники — 1 строка,
  // ей это не нужно: KPI уже показан отдельно)
  const showClinicsGrid = clinicsHealth.length > 1

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Шапка */}
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">🏥</span>
          <span className="font-bold text-brand-600 text-lg">ZMed Stock</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button
            onClick={signout}
            className="text-sm text-gray-400 hover:text-red-500 transition-colors"
          >
            Выйти
          </button>
        </div>
      </header>

      {/* Основной контент */}
      <main className="max-w-2xl mx-auto px-4 py-10">
        <h1 className="text-2xl font-bold text-gray-800 mb-2">Выберите раздел</h1>
        <p className="text-gray-500 text-sm mb-8">
          Вам доступно {availableModules.length} из {ALL_MODULES.length} разделов
        </p>

        {availableModules.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <div className="text-5xl mb-4">🔒</div>
            <p className="text-lg font-medium">Нет доступных разделов</p>
            <p className="text-sm mt-1">Обратитесь к администратору</p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {availableModules.map((m) => (
              <button
                key={m.id}
                onClick={() => navigate(m.path)}
                className="flex items-center gap-4 bg-white rounded-2xl p-5 shadow-sm
                           border border-gray-100 hover:shadow-md hover:border-brand-200
                           transition-all text-left group"
              >
                <div
                  className={`w-14 h-14 rounded-xl bg-gradient-to-br ${m.color}
                               flex items-center justify-center flex-shrink-0
                               group-hover:scale-105 transition-transform`}
                >
                  <m.Icon />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-gray-800 text-base">{m.title}</div>
                  <div className="text-sm text-gray-500 mt-0.5">{m.description}</div>
                </div>
                <svg
                  className="w-5 h-5 text-gray-300 group-hover:text-brand-400 transition-colors flex-shrink-0"
                  fill="none" viewBox="0 0 24 24" stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            ))}
          </div>
        )}

        {/* F38: уведомление «Требует разбора» */}
        {hasReports && reviewCount > 0 && (
          <button
            onClick={() => navigate('/clinic-reports?tag=' + encodeURIComponent('Требует разбора'))}
            className="mt-6 w-full flex items-center justify-between gap-3 bg-amber-50 border border-amber-200 rounded-xl p-3 text-sm text-amber-900 hover:bg-amber-100 transition"
          >
            <span>
              📝 Требует разбора: <strong>{reviewCount}</strong> отчёт(ов)
            </span>
            <span className="text-xs">Открыть →</span>
          </button>
        )}

        {/* F39: KPI активности текущего scope */}
        {hasReports && myActivity && (
          <section className="mt-6 grid grid-cols-3 gap-2">
            <div className="bg-white rounded-xl border p-3 text-center">
              <div className="text-xs text-gray-500">За 7 дней</div>
              <div className="text-2xl font-bold text-rose-600">
                {myActivity.reports_7d}
              </div>
              <div className="text-xs text-gray-400">отчётов</div>
            </div>
            <div className="bg-white rounded-xl border p-3 text-center">
              <div className="text-xs text-gray-500">За 30 дней</div>
              <div className="text-2xl font-bold text-brand-600">
                {myActivity.reports_30d}
              </div>
              <div className="text-xs text-gray-400">
                импл: {myActivity.implants_30d}
              </div>
            </div>
            <div className="bg-white rounded-xl border p-3 text-center">
              <div className="text-xs text-gray-500">Последний</div>
              <div className="text-base font-semibold text-gray-700 mt-1">
                {myActivity.last_report_date || '—'}
              </div>
            </div>
          </section>
        )}

        {/* F40: цветовая карта клиник (видна только ZMed-staff) */}
        {hasReports && showClinicsGrid && (
          <section className="mt-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-gray-700">
                Клиники · статус за 30 дней
              </h2>
              <button onClick={() => navigate('/clinic-analytics')}
                      className="text-xs text-brand-600 hover:text-brand-700">
                Аналитика →
              </button>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {clinicsHealth.map((c) => {
                const meta = HEALTH_META[c.health] || HEALTH_META.no_data
                return (
                  <div key={c.organization_id}
                       className={`border rounded-lg p-3 text-sm ${meta.cls}`}>
                    <div className="font-medium">{c.name}</div>
                    <div className="flex justify-between text-xs mt-1 opacity-90">
                      <span>{meta.label}</span>
                      <span>
                        отчётов: <strong>{c.reports}</strong>
                        {c.losses_qty > 0 && (
                          <> · потерь: <strong>{c.losses_qty}</strong></>
                        )}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        )}

        {hasReports && recentReports.length > 0 && (
          <section className="mt-10">
            <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-gray-800">Последние отчёты</h2>
              <button onClick={() => navigate('/clinic-reports')}
                      className="text-sm font-medium text-rose-600 hover:text-rose-700">
                Все отчёты →
              </button>
            </div>
            <div className="space-y-2">
              {recentReports.map((r) => (
                <button key={r.id}
                        onClick={() => navigate(`/clinic-reports/${r.id}`)}
                        className="block w-full text-left bg-white rounded-xl border hover:border-rose-300 hover:shadow p-3 transition">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div className="font-medium text-gray-800 text-sm">
                      #{r.id} · {r.operation_date} · {r.operation_type}
                    </div>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      r.status === 'draft'
                        ? 'bg-amber-100 text-amber-800'
                        : 'bg-emerald-100 text-emerald-800'
                    }`}>
                      {r.status === 'draft' ? 'Черновик' : 'Отправлен'}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    👨‍⚕️ {r.doctor_name} · 🧾 {r.patient_code}
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}

        {canSeeOrders && recentOrders.length > 0 && (
          <section className="mt-10">
            <div className="flex items-center justify-between mb-4 gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-gray-800">Последние заказы</h2>
              <div className="flex items-center gap-3 text-sm font-medium">
                {hasImplants && (
                  <button
                    onClick={() => navigate('/orders')}
                    className="text-brand-600 hover:text-brand-700"
                  >
                    Импланты →
                  </button>
                )}
                {hasSupplies && (
                  <button
                    onClick={() => navigate('/supplies/orders')}
                    className="text-teal-600 hover:text-teal-700"
                  >
                    Инструменты →
                  </button>
                )}
              </div>
            </div>
            <div className="space-y-3">
              {recentOrders.map((order) => (
                <OrderCard key={order.id} order={order} />
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}
