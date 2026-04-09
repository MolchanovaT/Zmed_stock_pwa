import { useState, useEffect } from 'react'
import {
  getGroups, getRegions, getWarehouses,
  getCategories, getManufacturers, getBrands, getNomTypes,
} from '../api/stock'

const ALL = 'все'

/**
 * Боковая панель с 7 каскадными выпадающими фильтрами.
 * Каждый следующий фильтр загружается только после выбора предыдущего.
 *
 * Props:
 *   onFiltersChange(filters) — вызывается при изменении любого фильтра
 *   disabled                 — блокировать панель во время загрузки результатов
 */
export default function FilterPanel({ onFiltersChange, disabled }) {
  const [filters, setFilters] = useState({
    group: '', region: '', warehouse: '', category: '',
    manufacturer: '', brand: '', nom_type: '',
  })

  const [options, setOptions] = useState({
    groups: [], regions: [], warehouses: [], categories: [],
    manufacturers: [], brands: [], nom_types: [],
  })

  const [loading, setLoading] = useState({})

  // ── Загружаем группы при монтировании ──────────────────────────────────────
  useEffect(() => {
    setLoading((l) => ({ ...l, groups: true }))
    getGroups()
      .then((items) => setOptions((o) => ({ ...o, groups: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, groups: false })))
  }, [])

  // ── При изменении группы — загружаем регионы ────────────────────────────────
  useEffect(() => {
    if (!filters.group) return
    const newF = { ...filters, region: '', warehouse: '', category: '', manufacturer: '', brand: '', nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, regions: [], warehouses: [], categories: [], manufacturers: [], brands: [], nom_types: [] }))
    setLoading((l) => ({ ...l, regions: true }))
    getRegions(filters.group)
      .then((items) => setOptions((o) => ({ ...o, regions: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, regions: false })))
    onFiltersChange(newF)
  }, [filters.group]) // eslint-disable-line

  useEffect(() => {
    if (!filters.region) return
    const newF = { ...filters, warehouse: '', category: '', manufacturer: '', brand: '', nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, warehouses: [], categories: [], manufacturers: [], brands: [], nom_types: [] }))
    setLoading((l) => ({ ...l, warehouses: true }))
    getWarehouses(filters.group, filters.region)
      .then((items) => setOptions((o) => ({ ...o, warehouses: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, warehouses: false })))
    onFiltersChange(newF)
  }, [filters.region]) // eslint-disable-line

  useEffect(() => {
    if (!filters.warehouse) return
    const newF = { ...filters, category: '', manufacturer: '', brand: '', nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, categories: [], manufacturers: [], brands: [], nom_types: [] }))
    setLoading((l) => ({ ...l, categories: true }))
    getCategories(filters.group, filters.region, filters.warehouse)
      .then((items) => setOptions((o) => ({ ...o, categories: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, categories: false })))
    onFiltersChange(newF)
  }, [filters.warehouse]) // eslint-disable-line

  useEffect(() => {
    if (!filters.category) return
    const newF = { ...filters, manufacturer: '', brand: '', nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, manufacturers: [], brands: [], nom_types: [] }))
    setLoading((l) => ({ ...l, manufacturers: true }))
    getManufacturers(filters.group, filters.region, filters.warehouse, filters.category)
      .then((items) => setOptions((o) => ({ ...o, manufacturers: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, manufacturers: false })))
    onFiltersChange(newF)
  }, [filters.category]) // eslint-disable-line

  useEffect(() => {
    if (!filters.manufacturer) return
    const newF = { ...filters, brand: '', nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, brands: [], nom_types: [] }))
    setLoading((l) => ({ ...l, brands: true }))
    getBrands(filters.group, filters.region, filters.warehouse, filters.category, filters.manufacturer)
      .then((items) => setOptions((o) => ({ ...o, brands: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, brands: false })))
    onFiltersChange(newF)
  }, [filters.manufacturer]) // eslint-disable-line

  useEffect(() => {
    if (!filters.brand) return
    const newF = { ...filters, nom_type: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, nom_types: [] }))
    setLoading((l) => ({ ...l, nom_types: true }))
    getNomTypes(filters.group, filters.region, filters.warehouse, filters.category, filters.manufacturer, filters.brand)
      .then((items) => setOptions((o) => ({ ...o, nom_types: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, nom_types: false })))
    onFiltersChange(newF)
  }, [filters.brand]) // eslint-disable-line

  const handleChange = (field) => (e) => {
    const value = e.target.value
    setFilters((f) => ({ ...f, [field]: value }))
  }

  // Уведомляем родителя о финальном выборе nom_type
  useEffect(() => {
    if (filters.nom_type !== undefined) onFiltersChange(filters)
  }, [filters.nom_type]) // eslint-disable-line

  const sel = (label, field, opts, isLoading) => (
    <div className="mb-3">
      <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
        {label}
      </label>
      <select
        disabled={disabled || isLoading || opts.length === 0}
        value={filters[field]}
        onChange={handleChange(field)}
        className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm
                   focus:outline-none focus:ring-2 focus:ring-brand-500
                   disabled:bg-gray-100 disabled:text-gray-400"
      >
        <option value="">
          {isLoading ? 'Загрузка...' : opts.length === 0 ? '—' : '— выберите —'}
        </option>
        {opts.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  )

  return (
    <div className="space-y-1 p-3 bg-white rounded-lg shadow-sm border border-gray-100">
      <h2 className="font-bold text-brand-600 mb-4 text-sm uppercase tracking-wide">Фильтры</h2>
      {sel('1. Группа складов', 'group', options.groups, loading.groups)}
      {sel('2. Регион', 'region', options.regions, loading.regions)}
      {sel('3. Склад', 'warehouse', options.warehouses, loading.warehouses)}
      {sel('4. Категория', 'category', options.categories, loading.categories)}
      {sel('5. Производитель', 'manufacturer', options.manufacturers, loading.manufacturers)}
      {sel('6. Марка (бренд)', 'brand', options.brands, loading.brands)}
      {sel('7. Вид номенклатуры', 'nom_type', options.nom_types, loading.nom_types)}
    </div>
  )
}
