import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { checkInn, addPending } from '../api/inn_check'

const STATUS_CONFIG = {
  approved:    { icon: '✅', text: 'Отгрузка одобрена',              color: 'bg-green-50 border-green-200 text-green-800' },
  denied:      { icon: '❌', text: 'Отгрузка запрещена',             color: 'bg-red-50 border-red-200 text-red-800' },
  denied_date: { icon: '❌', text: 'Отгрузка запрещена',             color: 'bg-red-50 border-red-200 text-red-800' },
  pending:     { icon: '⌛', text: 'Заявка на рассмотрении',         color: 'bg-yellow-50 border-yellow-200 text-yellow-800' },
  not_found:   { icon: '🔍', text: 'Отсутствует в перечне',          color: 'bg-gray-50 border-gray-200 text-gray-700' },
}

export default function InnCheckPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [orgType, setOrgType] = useState('')   // 'diler' | 'lpu'
  const [inn, setInn] = useState('')
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // Форма добавления заявки
  const [showPendingForm, setShowPendingForm] = useState(false)
  const [pendingName, setPendingName] = useState('')
  const [pendingLoading, setPendingLoading] = useState(false)
  const [pendingDone, setPendingDone] = useState(false)

  const handleCheck = async () => {
    if (!orgType) { setError('Выберите тип контрагента'); return }
    const trimmed = inn.trim()
    if (!trimmed) { setError('Введите ИНН'); return }

    setError('')
    setResult(null)
    setShowPendingForm(false)
    setPendingDone(false)
    setLoading(true)
    try {
      const data = await checkInn(trimmed, orgType)
      setResult(data)
      // Если не найден — предлагаем подать заявку
      if (data.status === 'not_found') setShowPendingForm(true)
    } catch {
      setError('Ошибка соединения с сервером')
    } finally {
      setLoading(false)
    }
  }

  const handleAddPending = async () => {
    if (!pendingName.trim()) return
    setPendingLoading(true)
    try {
      await addPending(pendingName.trim(), inn.trim())
      setPendingDone(true)
      setShowPendingForm(false)
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка при отправке заявки')
    } finally {
      setPendingLoading(false)
    }
  }

  const handleReset = () => {
    setOrgType('')
    setInn('')
    setResult(null)
    setError('')
    setShowPendingForm(false)
    setPendingName('')
    setPendingDone(false)
  }

  const cfg = result ? STATUS_CONFIG[result.status] : null

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Шапка */}
      <header className="bg-violet-600 text-white px-4 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate('/home')}
            className="text-white/80 hover:text-white transition-colors text-sm"
          >
            ← Главная
          </button>
          <h1 className="font-bold text-lg">Проверка контрагентов</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="hidden md:inline text-white/70">{user?.username}</span>
          <button onClick={signout} className="text-white/70 hover:text-white transition-colors">
            Выйти
          </button>
        </div>
      </header>

      <main className="flex-1 flex items-start justify-center px-4 py-10">
        <div className="w-full max-w-md">

          {/* Карточка поиска */}
          <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
            <h2 className="font-semibold text-gray-800 mb-5 text-base">
              Проверка отгрузки по ИНН
            </h2>

            {/* Тип контрагента */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">
                Тип контрагента
              </label>
              <div className="flex gap-2">
                {[
                  { value: 'diler', label: 'Дилер' },
                  { value: 'lpu',   label: 'ЛПУ' },
                ].map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => { setOrgType(opt.value); setResult(null); setError('') }}
                    className={`flex-1 py-2.5 rounded-lg border text-sm font-medium transition-colors
                      ${orgType === opt.value
                        ? 'bg-violet-600 border-violet-600 text-white'
                        : 'bg-white border-gray-300 text-gray-700 hover:border-violet-400'
                      }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Поле ИНН */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
                ИНН контрагента
              </label>
              <input
                type="text"
                inputMode="numeric"
                value={inn}
                onChange={(e) => { setInn(e.target.value); setResult(null); setError('') }}
                onKeyDown={(e) => e.key === 'Enter' && handleCheck()}
                placeholder="Введите ИНН..."
                className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm
                           focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
            </div>

            {error && (
              <p className="text-sm text-red-500 mb-3 text-center">{error}</p>
            )}

            <button
              onClick={handleCheck}
              disabled={loading}
              className="w-full bg-violet-600 hover:bg-violet-700 disabled:opacity-50
                         text-white font-semibold py-2.5 rounded-lg transition-colors"
            >
              {loading ? 'Проверяю...' : 'Проверить'}
            </button>
          </div>

          {/* Результат */}
          {cfg && (
            <div className={`mt-4 rounded-2xl border p-5 ${cfg.color}`}>
              <div className="flex items-center gap-3 mb-1">
                <span className="text-2xl">{cfg.icon}</span>
                <span className="font-semibold text-base">{cfg.text}</span>
              </div>
              {result.name && (
                <p className="text-sm mt-1 ml-9">{result.name}</p>
              )}
              {result.date && (
                <p className="text-sm mt-0.5 ml-9 opacity-75">
                  {result.status === 'pending' ? `Подано: ${result.date}` : `Дата запрета: ${result.date}`}
                </p>
              )}
              <button
                onClick={handleReset}
                className="mt-3 ml-9 text-xs underline opacity-60 hover:opacity-100 transition-opacity"
              >
                Новая проверка
              </button>
            </div>
          )}

          {/* Форма добавления заявки */}
          {showPendingForm && !pendingDone && (
            <div className="mt-4 bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
              <p className="text-sm font-medium text-gray-700 mb-3">
                Контрагент не найден. Отправить заявку на добавление?
              </p>
              <input
                type="text"
                value={pendingName}
                onChange={(e) => setPendingName(e.target.value)}
                placeholder="Название организации"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm mb-3
                           focus:outline-none focus:ring-2 focus:ring-violet-500"
              />
              <button
                onClick={handleAddPending}
                disabled={pendingLoading || !pendingName.trim()}
                className="w-full bg-violet-600 hover:bg-violet-700 disabled:opacity-50
                           text-white font-semibold py-2.5 rounded-lg transition-colors text-sm"
              >
                {pendingLoading ? 'Отправляю...' : 'Отправить заявку'}
              </button>
            </div>
          )}

          {pendingDone && (
            <div className="mt-4 rounded-2xl border bg-blue-50 border-blue-200 text-blue-800 p-5 text-sm text-center">
              ✅ Заявка отправлена на рассмотрение
            </div>
          )}

        </div>
      </main>
    </div>
  )
}
