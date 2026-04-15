import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'

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
]

/* ── Страница ────────────────────────────────────────────────────────────── */

export default function HomePage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const availableModules = ALL_MODULES.filter(
    (m) => user?.modules?.includes(m.id)
  )

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
      </main>
    </div>
  )
}
