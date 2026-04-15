import { useState, useEffect } from 'react'
import {
  getSuppliesGroups, getSuppliesRegions, getSuppliesWarehouses,
  getSuppliesCategories, getSuppliesManufacturers, getSuppliesBrands,
} from '../api/supplies'

const ALL = 'все'

/**
 * Боковая панель с 6 каскадными фильтрами для модуля «Расходники».
 * Props:
 *   onFiltersChange(filters) — вызывается при изменении любого фильтра
 *   disabled                 — блокировать панель во время загрузки результатов
 */
export default function SuppliesFilterPanel({ onFiltersChange, disabled }) {
  const [filters, setFilters] = useState({
    group: '', region: '', warehouse: '', category: '', manufacturer: '', brand: '',
  })

  const [options, setOptions] = useState({
    groups: [], regions: [], warehouses: [], categories: [], manufacturers: [], brands: [],
  })

  const [loading, setLoading] = useState({})

  useEffect(() => {
    setLoading((l) => ({ ...l, groups: true }))
    getSuppliesGroups()
      .then((items) => setOptions((o) => ({ ...o, groups: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, groups: false })))
  }, [])

  useEffect(() => {
    if (!filters.group) return
    const newF = { ...filters, region: '', warehouse: '', category: '', manufacturer: '', brand: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, regions: [], warehouses: [], categories: [], manufacturers: [], brands: [] }))
    setLoading((l) => ({ ...l, regions: true }))
    getSuppliesRegions(filters.group)
      .then((items) => setOptions((o) => ({ ...o, regions: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, regions: false })))
    onFiltersChange(newF)
  }, [filters.group]) // eslint-disable-line

  useEffect(() => {
    if (!filters.region) return
    const newF = { ...filters, warehouse: '', category: '', manufacturer: '', brand: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, warehouses: [], categories: [], manufacturers: [], brands: [] }))
    setLoading((l) => ({ ...l, warehouses: true }))
    getSuppliesWarehouses(filters.group, filters.region)
      .then((items) => setOptions((o) => ({ ...o, warehouses: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, warehouses: false })))
    onFiltersChange(newF)
  }, [filters.region]) // eslint-disable-line

  useEffect(() => {
    if (!filters.warehouse) return
    const newF = { ...filters, category: '', manufacturer: '', brand: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, categories: [], manufacturers: [], brands: [] }))
    setLoading((l) => ({ ...l, categories: true }))
    getSuppliesCategories(filters.group, filters.region, filters.warehouse)
      .then((items) => setOptions((o) => ({ ...o, categories: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, categories: false })))
    onFiltersChange(newF)
  }, [filters.warehouse]) // eslint-disable-line

  useEffect(() => {
    if (!filters.category) return
    const newF = { ...filters, manufacturer: '', brand: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, manufacturers: [], brands: [] }))
    setLoading((l) => ({ ...l, manufacturers: true }))
    getSuppliesManufacturers(filters.group, filters.region, filters.warehouse, filters.category)
      .then((items) => setOptions((o) => ({ ...o, manufacturers: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, manufacturers: false })))
    onFiltersChange(newF)
  }, [filters.category]) // eslint-disable-line

  useEffect(() => {
    if (!filters.manufacturer) return
    const newF = { ...filters, brand: '' }
    setFilters(newF)
    setOptions((o) => ({ ...o, brands: [] }))
    setLoading((l) => ({ ...l, brands: true }))
    getSuppliesBrands(filters.group, filters.region, filters.warehouse, filters.category, filters.manufacturer)
      .then((items) => setOptions((o) => ({ ...o, brands: [ALL, ...items] })))
      .finally(() => setLoading((l) => ({ ...l, brands: false })))
    onFiltersChange(newF)
  }, [filters.manufacturer]) // eslint-disable-line

  useEffect(() => {
    if (filters.brand !== undefined) onFiltersChange(filters)
  }, [filters.brand]) // eslint-disable-line

  const handleChange = (field) => (e) => {
    const value = e.target.value
    setFilters((f) => ({ ...f, [field]: value }))
  }

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
                   focus:outline-none focus:ring-2 focus:ring-teal-500
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
      <h2 className="font-bold text-teal-600 mb-4 text-sm uppercase tracking-wide">Фильтры</h2>
      {sel('1. Группа складов', 'group', options.groups, loading.groups)}
      {sel('2. Регион', 'region', options.regions, loading.regions)}
      {sel('3. Склад', 'warehouse', options.warehouses, loading.warehouses)}
      {sel('4. Категория', 'category', options.categories, loading.categories)}
      {sel('5. Производитель', 'manufacturer', options.manufacturers, loading.manufacturers)}
      {sel('6. Марка (бренд)', 'brand', options.brands, loading.brands)}
    </div>
  )
}
