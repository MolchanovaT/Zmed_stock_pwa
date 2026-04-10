import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import FilterPanel from '../components/FilterPanel'
import StockTable from '../components/StockTable'
import { searchStock, exportPdf } from '../api/stock'
import { addItem, getCart } from '../api/cart'

export default function SearchPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [filters, setFilters] = useState({})
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)  // мобильный сайдбар
  const [toast, setToast] = useState('')
  const [cartCount, setCartCount] = useState(0)

  useEffect(() => {
    getCart().then((cart) => setCartCount(cart?.items?.length ?? 0)).catch(() => {})
  }, [])

  // ── Выполняем поиск при изменении фильтров/страницы ────────────────────────
  const doSearch = useCallback(
    async (newFilters, newPage, newSearch) => {
      const f = newFilters ?? filters
      const p = newPage ?? page
      const s = newSearch ?? search

      // Если нет ни одного фильтра — не ищем
      const hasFilter = Object.values(f).some((v) => v && v !== 'все')
      if (!hasFilter && !s) {
        setResult(null)
        return
      }

      setLoading(true)
      try {
        const data = await searchStock({ ...f, search: s || undefined, page: p, per_page: 20 })
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

  const handleSearchInput = (e) => {
    const val = e.target.value
    setSearch(val)
    setPage(1)
    doSearch(filters, 1, val)
  }

  const handlePageChange = (p) => {
    setPage(p)
    doSearch(filters, p, search)
  }

  // ── Добавить в корзину ──────────────────────────────────────────────────────
  const handleAddToCart = async (item) => {
    try {
      await addItem({
        article: item.article,
        nomenclature: item.nomenclature,
        characteristic: item.characteristic,
        quantity: 1,
        available_balance: item.balance,
        lpu: '',
      })
      setCartCount((n) => n + 1)
      showToast(`✅ Добавлено: ${item.nomenclature.slice(0, 30)}...`)
    } catch {
      showToast('❌ Ошибка добавления в корзину')
    }
  }

  const showToast = (msg) => {
    setToast(msg)
    setTimeout(() => setToast(''), 3000)
  }

  const handlePdf = async () => {
    setPdfLoading(true)
    try {
      await exportPdf({ ...filters, search: search || undefined })
    } catch {
      showToast('❌ Ошибка генерации PDF')
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ── Шапка ───────────────────────────────────────────────────────────── */}
      <header className="bg-brand-500 text-white px-4 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          {/* Кнопка фильтров (мобильная) */}
          <button
            className="md:hidden text-white text-xl"
            onClick={() => setFiltersOpen((o) => !o)}
          >
            ☰
          </button>
          <h1 className="font-bold text-lg">ZMed Stock</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <button
            onClick={() => navigate('/orders')}
            className="bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg transition-colors"
          >
            📋 Заказы
          </button>
          <button
            onClick={() => navigate('/cart')}
            className="relative bg-white/20 hover:bg-white/30 px-3 py-1.5 rounded-lg transition-colors"
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
          <span className="hidden md:inline text-white/70">{user?.username}</span>
          <button
            onClick={signout}
            className="text-white/70 hover:text-white transition-colors"
          >
            Выйти
          </button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Боковая панель фильтров ──────────────────────────────────────── */}
        {/* Мобильное наложение */}
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
            <FilterPanel
              onFiltersChange={handleFiltersChange}
              disabled={loading}
            />
          </div>
        </aside>

        {/* ── Основная область ─────────────────────────────────────────────── */}
        <main className="flex-1 flex flex-col overflow-hidden p-3 gap-3">
          {/* Строка поиска + кнопки */}
          <div className="flex gap-2 flex-wrap">
            <input
              type="text"
              value={search}
              onChange={handleSearchInput}
              placeholder="Поиск по названию, артикулу..."
              className="flex-1 min-w-0 border border-gray-300 rounded-lg px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
            <button
              onClick={handlePdf}
              disabled={pdfLoading || !result}
              className="bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-40
                         text-sm px-3 py-2 rounded-lg transition-colors whitespace-nowrap"
            >
              {pdfLoading ? '...' : '📄 PDF'}
            </button>
          </div>

          {/* Таблица результатов */}
          <div className="flex-1 overflow-hidden">
            <StockTable
              result={result}
              loading={loading}
              page={page}
              onPageChange={handlePageChange}
              onAddToCart={handleAddToCart}
            />
          </div>
        </main>
      </div>

      {/* Toast-уведомление */}
      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50
                        bg-gray-800 text-white text-sm px-4 py-2 rounded-lg shadow-lg
                        animate-fade-in">
          {toast}
        </div>
      )}
    </div>
  )
}
