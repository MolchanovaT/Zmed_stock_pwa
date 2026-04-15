import React, { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import SuppliesFilterPanel from '../components/SuppliesFilterPanel'
import { searchSupplies, exportSuppliesPdf } from '../api/supplies'

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

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      {/* ── Шапка ───────────────────────────────────────────────────────────── */}
      <header className="bg-teal-600 text-white px-4 py-3 flex items-center justify-between shadow-md">
        <div className="flex items-center gap-3">
          <button
            className="md:hidden text-white text-xl"
            onClick={() => setFiltersOpen((o) => !o)}
          >
            ☰
          </button>
          <button
            onClick={() => navigate('/home')}
            className="text-white/80 hover:text-white transition-colors text-sm mr-1"
            title="На главную"
          >
            ← Главная
          </button>
          <h1 className="font-bold text-lg">Расходники и инструменты</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
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
        {/* Мобильное наложение */}
        {filtersOpen && (
          <div
            className="fixed inset-0 bg-black/30 z-20 md:hidden"
            onClick={() => setFiltersOpen(false)}
          />
        )}
        {/* ── Боковая панель фильтров ──────────────────────────────────────── */}
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

        {/* ── Основная область ─────────────────────────────────────────────── */}
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
                  {items.map((item, idx) => (
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
                        <div className="text-right flex-shrink-0">
                          <div className="font-bold text-teal-600 text-sm">
                            {item.balance.toLocaleString('ru-RU')}
                          </div>
                          <div className="text-xs text-gray-400">ост.</div>
                        </div>
                      </div>
                    </div>
                  ))}
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
