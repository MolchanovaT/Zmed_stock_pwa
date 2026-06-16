import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { getOrders } from '../api/cart'
import OrderCard from '../components/OrderCard'

const KIND_CONFIG = {
  implants: {
    title: 'Мои заказы',
    searchPath: '/',
    cartPath: '/cart',
    headerClass: 'bg-brand-500',
    primaryBtnClass: 'bg-brand-500 hover:bg-brand-600',
  },
  supplies: {
    title: 'Заказы расходников',
    searchPath: '/supplies',
    cartPath: '/supplies/cart',
    headerClass: 'bg-teal-600',
    primaryBtnClass: 'bg-teal-600 hover:bg-teal-700',
  },
}

export default function OrdersPage({ kind = 'implants' }) {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const cfg = KIND_CONFIG[kind] ?? KIND_CONFIG.implants

  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    getOrders(kind)
      .then(setOrders)
      .catch(() => setError('Ошибка загрузки заказов'))
      .finally(() => setLoading(false))
  }, [kind])

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className={`${cfg.headerClass} text-white px-4 py-3 flex items-center justify-between shadow-md`}>
        <div className="flex items-center gap-3">
          <button onClick={() => navigate(cfg.searchPath)} className="text-white/80 hover:text-white">
            ← Поиск
          </button>
          <h1 className="font-bold text-lg">{cfg.title}</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => navigate(cfg.cartPath)}
            className="bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg transition-colors"
          >
            🛒 Корзина
          </button>
          <span className="text-white/70 hidden md:inline">{user?.username}</span>
          <button onClick={signout} className="text-white/70 hover:text-white">
            Выйти
          </button>
        </div>
      </header>

      <main className="flex-1 p-4 max-w-2xl mx-auto w-full">
        {loading && (
          <div className="text-center py-16 text-gray-400">Загрузка...</div>
        )}

        {error && (
          <p className="text-sm text-red-500 bg-red-50 rounded-lg px-3 py-2">{error}</p>
        )}

        {!loading && !error && orders.length === 0 && (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">📋</div>
            <p className="text-gray-500 mb-6">Заказов пока нет</p>
            <button
              onClick={() => navigate(cfg.searchPath)}
              className={`${cfg.primaryBtnClass} text-white px-6 py-2.5
                         rounded-lg font-semibold transition-colors`}
            >
              Начать поиск
            </button>
          </div>
        )}

        {!loading && orders.length > 0 && (
          <div className="space-y-3">
            {orders.map((order) => (
              <OrderCard key={order.id} order={order} />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
