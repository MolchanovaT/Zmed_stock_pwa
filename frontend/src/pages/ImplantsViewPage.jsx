import React, { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import FilterPanel from '../components/FilterPanel'
import StockTable from '../components/StockTable'
import { searchStock, exportPdf } from '../api/stock'

export default function ImplantsViewPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [filters, setFilters] = useState({})
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [toast, setToast] = useState('')

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
        const data = await searchStock({ ...f, search: s || undefined, page: p, per_page: 20 }, 'implants_view')
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

  const handlePdf = async () => {
    setPdfLoading(true)
    try {
      await exportPdf({ ...filters, search: search || undefined }, 'implants_view')
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
          <button
            className="md:hidden text-white text-xl"
            onClick={() => setFiltersOpen((o) => !o)}
          >
            ☰
          </button>
          <button
            onClick={() => navigate('/home')}
            className="text-white/80 hover:text-white transition-colors text-sm"
          >
            ← Главная
          </button>
          <h1 className="font-bold text-lg">Импланты — просмотр</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="hidden md:inline text-white/70">{user?.username}</span>
          <button onClick={signout} className="text-white/70 hover:text-white transition-colors">
            Выйти
          </button>
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
            <FilterPanel onFiltersChange={handleFiltersChange} disabled={loading} />
          </div>
        </aside>

        <main className="flex-1 flex flex-col overflow-hidden p-3 gap-3">
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

          <div className="flex-1 overflow-hidden">
            {/* onAddToCart не передаём — кнопка корзины не показывается */}
            <StockTable
              result={result}
              loading={loading}
              page={page}
              onPageChange={handlePageChange}
            />
          </div>
        </main>
      </div>

      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50
                        bg-gray-800 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
          {toast}
        </div>
      )}
    </div>
  )
}
