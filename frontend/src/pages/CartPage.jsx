import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import CartItem from '../components/CartItem'
import OrderForm from '../components/OrderForm'
import { getCart, placeOrder, clearCart } from '../api/cart'

export default function CartPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [cart, setCart] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [orderDone, setOrderDone] = useState(null)  // { order_id, message }
  const [error, setError] = useState('')

  const loadCart = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getCart()
      setCart(data)
    } catch {
      setError('Ошибка загрузки корзины')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadCart() }, [loadCart])

  const handleItemUpdate = useCallback((itemId, newQty) => {
    setCart((c) => ({
      ...c,
      items: c.items.map((it) => it.id === itemId ? { ...it, quantity: newQty } : it),
    }))
  }, [])

  const handleItemDelete = useCallback((itemId) => {
    setCart((c) => ({
      ...c,
      items: c.items.filter((it) => it.id !== itemId),
    }))
  }, [])

  const handleClearCart = async () => {
    if (!window.confirm('Очистить корзину? Все позиции будут удалены.')) return
    await clearCart()
    setCart(null)
  }

  const handlePlaceOrder = async (formData) => {
    setSubmitting(true)
    setError('')
    try {
      const result = await placeOrder(formData)
      setOrderDone(result)
      setCart(null)
      sessionStorage.removeItem('cart_region')
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка оформления заказа')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* Шапка */}
      <header className="bg-brand-500 text-white shadow-md">
        {/* Ряд 1: навигация */}
        <div className="px-4 pt-3 pb-1.5 flex items-center justify-between">
          <button onClick={() => navigate('/home')} className="text-white/80 hover:text-white transition-colors text-sm">
            ← Главная
          </button>
          <h1 className="font-bold text-lg">Корзина</h1>
          <button onClick={signout} className="text-white/70 hover:text-white transition-colors text-sm">
            Выйти
          </button>
        </div>
        {/* Ряд 2: действия */}
        <div className="px-4 pb-2.5 flex items-center justify-between text-sm">
          <button onClick={() => navigate('/')} className="text-white/80 hover:text-white transition-colors">
            ← Поиск
          </button>
          <button
            onClick={() => navigate('/orders')}
            className="bg-white/20 hover:bg-white/30 px-3 py-1 rounded-lg transition-colors"
          >
            📋 Заказы
          </button>
        </div>
      </header>

      <main className="flex-1 p-4 max-w-2xl mx-auto w-full">
        {/* Заказ оформлен */}
        {orderDone && (
          <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
            <div className="text-4xl mb-3">✅</div>
            <h2 className="text-xl font-bold text-green-700 mb-2">
              Заказ #{orderDone.order_id} оформлен!
            </h2>
            <p className="text-sm text-green-600 mb-4">{orderDone.message}</p>
            <button
              onClick={() => navigate('/')}
              className="bg-brand-500 hover:bg-brand-600 text-white px-6 py-2.5
                         rounded-lg font-semibold transition-colors"
            >
              🔍 Новый поиск
            </button>
          </div>
        )}

        {/* Загрузка */}
        {!orderDone && loading && (
          <div className="text-center py-16 text-gray-400">Загрузка...</div>
        )}

        {/* Корзина пуста */}
        {!orderDone && !loading && !cart && (
          <div className="text-center py-16">
            <div className="text-5xl mb-4">🛒</div>
            <p className="text-gray-500 mb-6">Корзина пуста</p>
            <button
              onClick={() => navigate('/')}
              className="bg-brand-500 hover:bg-brand-600 text-white px-6 py-2.5
                         rounded-lg font-semibold transition-colors"
            >
              Начать поиск
            </button>
          </div>
        )}

        {/* Корзина с позициями */}
        {!orderDone && !loading && cart && (
          <>
            {/* Заголовок корзины */}
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm text-gray-500">
                Заказ #{cart.id} &nbsp;|&nbsp; ЛПУ: <b>{cart.lpu || 'не указано'}</b>
                &nbsp;|&nbsp; Позиций: <b>{cart.items.length}</b>
              </p>
              <button
                onClick={handleClearCart}
                className="text-xs text-red-400 hover:text-red-600 border border-red-200
                           hover:border-red-400 rounded-lg px-2.5 py-1 transition-colors whitespace-nowrap"
              >
                Очистить
              </button>
            </div>

            {/* Список позиций, сгруппированных по номенклатуре */}
            <div className="space-y-3 mb-6">
              {Object.values(
                cart.items.reduce((acc, item) => {
                  const key = item.nomenclature
                  if (!acc[key]) acc[key] = { nomenclature: item.nomenclature, items: [] }
                  acc[key].items.push(item)
                  return acc
                }, {})
              ).map((group) => (
                <div key={group.nomenclature}
                     className="bg-white rounded-lg border border-gray-100 shadow-sm overflow-hidden">
                  {/* Заголовок группы */}
                  <div className="px-3 py-2 bg-gray-50 border-b border-gray-100">
                    <p className="text-sm font-semibold text-gray-800 leading-snug">{group.nomenclature}</p>
                  </div>
                  {/* Строки характеристик */}
                  <div className="divide-y divide-gray-50">
                    {group.items.map((item) => (
                      <CartItem
                        key={item.id}
                        item={item}
                        compact
                        onUpdate={handleItemUpdate}
                        onDelete={handleItemDelete}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Ошибка */}
            {error && (
              <p className="text-sm text-red-500 bg-red-50 rounded-lg px-3 py-2 mb-4">
                {error}
              </p>
            )}

            {/* Форма оформления */}
            {cart.items.length > 0 && (
              <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
                <OrderForm
                  onSubmit={handlePlaceOrder}
                  submitting={submitting}
                  initialLpu={cart.lpu || ''}
                  regionContext={sessionStorage.getItem('cart_region') || ''}
                />
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
