import { useState, useRef, useEffect } from 'react'

const ACCENT = {
  brand: { ring: 'focus:ring-brand-500', hover: 'hover:bg-brand-50', active: 'bg-brand-100' },
  teal:  { ring: 'focus:ring-teal-500',  hover: 'hover:bg-teal-50',  active: 'bg-teal-100'  },
}

/**
 * Выпадающий список с поиском по введённой подстроке.
 *
 * Props:
 *   value      — выбранное значение (строка)
 *   onChange   — (value) => void
 *   options    — массив строк
 *   disabled   — заблокировать поле
 *   isLoading  — режим загрузки (показывается «Загрузка...»)
 *   accent     — 'brand' | 'teal' (цвет фокуса/подсветки)
 */
export default function SearchableSelect({
  value,
  onChange,
  options,
  disabled = false,
  isLoading = false,
  accent = 'brand',
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef(null)

  useEffect(() => {
    const handler = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const isDisabled = disabled || isLoading || options.length === 0
  const colors = ACCENT[accent] || ACCENT.brand

  const q = query.trim().toLowerCase()
  const filtered = q
    ? options.filter((o) => String(o).toLowerCase().includes(q))
    : options

  const pick = (opt) => {
    onChange(opt)
    setOpen(false)
    setQuery('')
  }

  const placeholder = open
    ? 'Поиск...'
    : isLoading
      ? 'Загрузка...'
      : options.length === 0
        ? '—'
        : '— выберите —'

  return (
    <div ref={rootRef} className="relative">
      <input
        type="text"
        disabled={isDisabled}
        value={open ? query : (value || '')}
        placeholder={placeholder}
        onFocus={() => { if (!isDisabled) { setOpen(true); setQuery('') } }}
        onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
        className={`w-full border border-gray-300 rounded-md px-2 py-1.5 pr-7 text-sm
                    focus:outline-none focus:ring-2 ${colors.ring}
                    disabled:bg-gray-100 disabled:text-gray-400`}
      />
      <span className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs pointer-events-none">
        ▼
      </span>
      {open && !isDisabled && (
        <ul className="absolute z-20 mt-1 w-full max-h-60 overflow-auto bg-white border border-gray-300 rounded-md shadow-lg text-sm">
          {filtered.length === 0 ? (
            <li className="px-2 py-1.5 text-gray-400 italic">Ничего не найдено</li>
          ) : (
            filtered.map((o) => (
              <li
                key={o}
                onMouseDown={(e) => { e.preventDefault(); pick(o) }}
                className={`px-2 py-1.5 cursor-pointer ${colors.hover} ${o === value ? `${colors.active} font-semibold` : ''}`}
              >
                {o}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
