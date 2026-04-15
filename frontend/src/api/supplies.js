import client from './client'

// ── Фильтры ────────────────────────────────────────────────────────────────────

export const getSuppliesGroups = () =>
  client.get('/supplies/groups').then((r) => r.data.items)

export const getSuppliesRegions = (group) =>
  client.get('/supplies/regions', { params: { group } }).then((r) => r.data.items)

export const getSuppliesWarehouses = (group, region) =>
  client.get('/supplies/warehouses', { params: { group, region } }).then((r) => r.data.items)

export const getSuppliesCategories = (group, region, warehouse) =>
  client.get('/supplies/categories', { params: { group, region, warehouse } }).then((r) => r.data.items)

export const getSuppliesManufacturers = (group, region, warehouse, category) =>
  client
    .get('/supplies/manufacturers', { params: { group, region, warehouse, category } })
    .then((r) => r.data.items)

export const getSuppliesBrands = (group, region, warehouse, category, manufacturer) =>
  client
    .get('/supplies/brands', { params: { group, region, warehouse, category, manufacturer } })
    .then((r) => r.data.items)

// ── Поиск ─────────────────────────────────────────────────────────────────────

export const searchSupplies = (filters) =>
  client.get('/supplies/search', { params: filters }).then((r) => r.data)

// ── PDF-экспорт ────────────────────────────────────────────────────────────────

export async function exportSuppliesPdf(filters) {
  const token = localStorage.getItem('access_token')
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v) params.append(k, v)
  })

  const url = `/api/supplies/export-pdf?${params}`
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error('Ошибка генерации PDF')

  const blob = await response.blob()
  const blobUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.setAttribute('download', 'supplies_report.pdf')
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}
