import React, { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import SuppliesFilterPanel from '../components/SuppliesFilterPanel'
import { searchSupplies, exportSuppliesPdf } from '../api/supplies'
import { addItem, getCart } from '../api/cart'

const ROWS_PER_PAGE = 20

export default function SuppliesPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [filters, setFilters] = useState({})
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(null) // 'simple' | 'detail' | null
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [toast, setToast] = useState('')
  const [cartCount, setCartCount] = useState(0)
  const [addedKeys, setAddedKeys] = useState(() => new Set())

  // У расходников нет article — ключ строим по (nomenclature, characteristic, lpu)
  const itemKey = (nomenclature, characteristic, lpu) =>
    `${nomenclature || ''}|${characteristic || ''}|${lpu || ''}`

  useEffect(() => {
    getCart('supplies').then((cart) => {
      setCartCount(cart?.items?.length ?? 0)
      if (cart?.items?.length) {
        setAddedKeys(new Set(cart.items.map((ci) => itemKey(ci.nomenclature, ci.characteristic, ci.lpu))))
      }
    }).catch(() => {})
  }, [])

  const doSearch = useCallback(
    async (newFilters, newPage, newSearch) => {
      const f = newFilters ?? filters
      const p = newPage ?? page
      const s = newSearch ?? search

      const hasFilter = Object.values(f).some((v) => v && v !== 'все')
      if (!hasFilter && !s) {
        setResult(null)
        return
      }

      setLoading(true)
      try {
        const data = await searchSupplies({ ...f, search: s || undefined, page: p, per_page: ROWS_PER_PAGE })
        setResult(data)
        setPage(data.page)
      } finally {
        setLoading(false)
      }
    },
    [filters, page, search]
  )

  const handleFiltersChange = useCallback((newFilters) => {
    setFilters(newFilters)
    setPage(1)
    doSearch(newFilters, 1, search)
  }, [doSearch, search])

  const searchTimer = React.useRef(null)
  const handleSearchInput = (e) => {
    const val = e.target.value
    setSearch(val)
    setPage(1)
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => doSearch(filters, 1, val), 500)
  }

  const handlePageChange = (p) => {
    setPage(p)
    doSearch(filters, p, search)
  }

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const handleAddToCart = async (item) => {
    try {
      const warehouse = filters.warehouse && filters.warehouse !== 'все' ? filters.warehouse : ''
      if (filters.region && filters.region !== 'все') {
        sessionStorage.setItem('cart_region_supplies', filters.region)
      } else {
        sessionStorage.removeItem('cart_region_supplies')
      }
      await addItem({
        article: '',
        nomenclature: item.nomenclature,
        characteristic: item.characteristic || '',
        quantity: 1,
        available_balance: Number(item.balance) || 0,
        lpu: warehouse,
      }, 'supplies')
      setCartCount((n) => n + 1)
      setAddedKeys((s) => {
        const next = new Set(s)
        next.add(itemKey(item.nomenclature, item.characteristic, warehouse))
        return next
      })
      showToast(`✅ Добавлено: ${item.nomenclature.slice(0, 30)}...`)
    } catch {
      showToast('❌ Ошибка добавления в корзину')
    }
  }

  const handlePdf = async (detail) => {
    setPdfLoading(detail ? 'detail' : 'simple')
    try {
      await exportSuppliesPdf({ ...filters, search: search || undefined }, detail)
    } catch {
      showToast('❌ Ошибка генерации PDF')
    } finally {
      setPdfLoading(null)
    }
  }

  const { items = [], total = 0, total_pages = 1, updated_at } = result ?? {}
  const currentWarehouse = filters.warehouse && filters.warehouse !== 'все' ? filters.warehouse : ''

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ── Шапка ───────────────────────────────────────────────────────────── */}
      <header className="bg-teal-600 text-white shadow-md">
        {/* Ряд 1: навигация */}
        <div className="px-4 pt-3 pb-1.5 flex items-center justify-between">
          <button
            onClick={() => navigate('/home')}
            className="text-white/80 hover:text-white transition-colors text-sm"
          >
            ← Главная
          </button>
          <h1 className="font-bold text-lg">Расходники и инструменты</h1>
          <button onClick={signout} className="text-white/70 hover:text-white transition-colors text-sm">
            Выйти
          </button>
        </div>
        {/* Ряд 2: действия */}
        <div className="px-4 pb-2.5 flex items-center justify-between text-sm">
          <button
            className="md:hidden text-white/80 hover:text-white transition-colors flex items-center gap-1"
            onClick={() => setFiltersOpen((o) => !o)}
          >
            ☰ Фильтры
          </button>
          <div className="flex items-center gap-2 md:ml-auto">
            <button
              onClick={() => navigate('/supplies/orders')}
              className="bg-white/20 hover:bg-white/30 px-3 py-1 rounded-lg transition-colors"
            >
              📋 Заказы
            </button>
            <button
              onClick={() => navigate('/supplies/cart')}
              className="relative bg-white/20 hover:bg-white/30 px-3 py-1 rounded-lg transition-colors"
            >
              🛒 Корзина
              {cartCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 bg-red-500 text-white text-xs
                                 font-bold rounded-full min-w-[18px] h-[18px] flex items-center
                                 justify-center px-1 leading-none">
                  {cartCount}
                </span>
              )}
            </button>
          </div>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {filtersOpen && (
          <div
            className="fixed inset-0 bg-black/30 z-20 md:hidden"
            onClick={() => setFiltersOpen(false)}
          />
        )}
        <aside
          className={`
            fixed md:relative inset-y-0 left-0 z-30
            w-72 md:w-64 lg:w-72
            bg-gray-50 border-r border-gray-200
            transform transition-transform duration-200
            ${filtersOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
            overflow-y-auto
          `}
        >
          <div className="p-3">
            <SuppliesFilterPanel
              onFiltersChange={handleFiltersChange}
              disabled={loading}
            />
          </div>
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden p-3 gap-3">
          {/* Строка поиска + PDF */}
          <div className="flex gap-2 flex-wrap">
            <input
              type="text"
              value={search}
              onChange={handleSearchInput}
              placeholder="Поиск по названию, характеристике..."
              className="flex-1 min-w-0 border border-gray-300 rounded-lg px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-teal-500"
            />
            <button
              onClick={() => handlePdf(false)}
              disabled={pdfLoading !== null || !result}
              className="bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-40
                         text-sm px-3 py-2 rounded-lg transition-colors whitespace-nowrap"
            >
              {pdfLoading === 'simple' ? '...' : '📄 PDF Кратко'}
            </button>
            <button
              onClick={() => handlePdf(true)}
              disabled={pdfLoading !== null || !result}
              className="bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-40
                         text-sm px-3 py-2 rounded-lg transition-colors whitespace-nowrap"
            >
              {pdfLoading === 'detail' ? '...' : '📄 PDF Детально'}
            </button>
          </div>

          {/* Результаты */}
          <div className="flex-1 overflow-auto">
            {loading ? (
              <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
                Поиск...
              </div>
            ) : !result ? (
              <div className="flex items-center justify-center h-48 text-gray-300 text-sm">
                Выберите фильтры слева для отображения остатков
              </div>
            ) : items.length === 0 ? (
              <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
                Ничего не найдено
              </div>
            ) : (
              <>
                {/* Дата актуальности + счётчик */}
                <div className="flex items-center justify-between mb-2 text-xs text-gray-500">
                  <span>Найдено: {total}</span>
                  {updated_at && <span>Актуально на: {updated_at}</span>}
                </div>

                {/* Карточки */}
                <div className="flex flex-col gap-2">
                  {items.map((item, idx) => {
                    const added = addedKeys.has(itemKey(item.nomenclature, item.characteristic, currentWarehouse))
                    return (
                      <div
                        key={idx}
                        className="bg-white rounded-xl border border-gray-100 shadow-sm p-3"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="font-medium text-sm text-gray-800 leading-snug">
                              {item.nomenclature}
                            </div>
                            {item.characteristic && (
                              <div className="text-xs text-gray-500 mt-0.5">{item.characteristic}</div>
                            )}
                            {item.photo_url && (
                              <a
                                href={item.photo_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-teal-600 hover:underline mt-0.5 inline-block"
                              >
                                📷 Фото
                              </a>
                            )}
                          </div>
                          <div className="text-right flex-shrink-0 flex flex-col items-end gap-2">
                            <div>
                              <div className="font-bold text-teal-600 text-sm">
                                {Number(item.balance).toLocaleString('ru-RU')}
                              </div>
                              <div className="text-xs text-gray-400">ост.</div>
                            </div>
                            <button
                              onClick={() => handleAddToCart(item)}
                              className={`text-xs font-medium px-2.5 py-1 rounded-lg transition-colors whitespace-nowrap ${
                                added
                                  ? 'bg-green-500 hover:bg-green-600 text-white'
                                  : 'bg-teal-600 hover:bg-teal-700 text-white'
                              }`}
                            >
                              {added ? '✓ В корзине' : '+ В корзину'}
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Пагинация */}
                {total_pages > 1 && (
                  <div className="flex justify-center gap-2 mt-4">
                    <button
                      onClick={() => handlePageChange(page - 1)}
                      disabled={page <= 1}
                      className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-30
                                 hover:bg-gray-50 transition-colors"
                    >
                      ← Назад
                    </button>
                    <span className="px-3 py-1.5 text-sm text-gray-500">
                      {page} / {total_pages}
                    </span>
                    <button
                      onClick={() => handlePageChange(page + 1)}
                      disabled={page >= total_pages}
                      className="px-3 py-1.5 text-sm border rounded-lg disabled:opacity-30
                                 hover:bg-gray-50 transition-colors"
                    >
                      Вперёд →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50
                        bg-gray-800 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}
