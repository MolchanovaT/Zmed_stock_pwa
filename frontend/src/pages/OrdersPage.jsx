import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { getOrders } from '../api/cart'

function OrderCard({ order }) {
  const [open, setOpen] = useState(false)

  // Группировка позиций по наименованию
  const groups = Object.values(
    order.items.reduce((acc, item) => {
      const key = item.nomenclature
      if (!acc[key]) acc[key] = { nomenclature: item.nomenclature, items: [] }
      acc[key].items.push(item)
      return acc
    }, {})
  )

  const createdAt = order.created_at
    ? new Date(order.created_at).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '—'

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      {/* Шапка заказа */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left px-4 py-3 flex items-start justify-between gap-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-gray-800">Заказ #{order.id}</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              Оформлен
            </span>
          </div>
          <div className="mt-1 text-sm text-gray-500 space-y-0.5">
            <p>📅 Создан: {createdAt}</p>
            <p>🏥 ЛПУ: <span className="font-medium text-gray-700">{order.lpu || '—'}</span></p>
            {order.doctor && <p>👨‍⚕️ Врач: <span className="font-medium text-gray-700">{order.doctor}</span></p>}
            {order.delivery_date && (
              <p>🚚 Доставка: <span className="font-medium text-gray-700">{order.delivery_date} в {order.delivery_time}</span></p>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-sm text-gray-400">{order.items.length} поз.</p>
          <p className="text-lg mt-1">{open ? '▲' : '▼'}</p>
        </div>
      </button>

      {/* Позиции */}
      {open && (
        <div className="border-t border-gray-100">
          {groups.map((group) => (
            <div key={group.nomenclature}>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
                <p className="text-sm font-semibold text-gray-800">{group.nomenclature}</p>
              </div>
              {group.items.map((item) => (
                <div key={item.id}
                     className="flex items-center justify-between px-4 py-2 border-b border-gray-50 last:border-0">
                  <div className="min-w-0">
                    <div className="flex gap-2 items-baseline flex-wrap">
                      {item.article && (
                        <span className="font-mono text-xs text-gray-400">{item.article}</span>
                      )}
                      <span className="text-sm text-gray-600 truncate">{item.characteristic || '—'}</span>
                    </div>
                  </div>
                  <span className="shrink-0 ml-4 text-sm font-semibold text-gray-700">
                    × {item.quantity}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function OrdersPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getOrders()
      .then(setOrders)
      .catch(() => setError('Ошибка загрузки заказов'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-brand-500 text-white px-4 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/')} className="text-white/80 hover:text-white">
            ← Поиск
          </button>
          <h1 className="font-bold text-lg">Мои заказы</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => navigate('/cart')}
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
              onClick={() => navigate('/')}
              className="bg-brand-500 hover:bg-brand-600 text-white px-6 py-2.5
                         rounded-lg font-semibold transition-colors"
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
