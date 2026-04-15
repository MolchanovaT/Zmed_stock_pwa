import client from './client'

// ── Фильтры ────────────────────────────────────────────────────────────────────

export const getGroups = () =>
  client.get('/stock/groups').then((r) => r.data.items)

export const getRegions = (group) =>
  client.get('/stock/regions', { params: { group } }).then((r) => r.data.items)

export const getWarehouses = (group, region) =>
  client.get('/stock/warehouses', { params: { group, region } }).then((r) => r.data.items)

export const getCategories = (group, region, warehouse) =>
  client.get('/stock/categories', { params: { group, region, warehouse } }).then((r) => r.data.items)

export const getManufacturers = (group, region, warehouse, category) =>
  client
    .get('/stock/manufacturers', { params: { group, region, warehouse, category } })
    .then((r) => r.data.items)

export const getBrands = (group, region, warehouse, category, manufacturer) =>
  client
    .get('/stock/brands', { params: { group, region, warehouse, category, manufacturer } })
    .then((r) => r.data.items)

export const getNomTypes = (group, region, warehouse, category, manufacturer, brand) =>
  client
    .get('/stock/nom-types', { params: { group, region, warehouse, category, manufacturer, brand } })
    .then((r) => r.data.items)

/** Список складов для выбора ЛПУ при оформлении заказа. Фильтруется по региону если передан. */
export const getLpuList = (region = '') =>
  client.get('/stock/warehouses', { params: region ? { region } : {} }).then((r) => r.data.items)

// ── Поиск ─────────────────────────────────────────────────────────────────────

/**
 * Поиск остатков.
 * @param {Object} filters — все 7 фильтров + search, page, per_page
 * @returns {{ items, total, page, total_pages, updated_at }}
 */
export const searchStock = (filters, module = 'implants') =>
  client.get('/stock/search', { params: { ...filters, module } }).then((r) => r.data)

// ── PDF-экспорт ────────────────────────────────────────────────────────────────

/**
 * Скачивает PDF с результатами поиска.
 * Открывает скачивание в браузере.
 */
export async function exportPdf(filters, module = 'implants') {
  const token = localStorage.getItem('access_token')
  const params = new URLSearchParams()
  Object.entries({ ...filters, module }).forEach(([k, v]) => {
    if (v) params.append(k, v)
  })

  const url = `/api/stock/export-pdf?${params}`
  const link = document.createElement('a')
  link.href = url
  link.setAttribute('download', 'report.pdf')

  // Добавляем Bearer-заголовок через fetch, создаём blob-ссылку
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error('Ошибка генерации PDF')

  const blob = await response.blob()
  const blobUrl = URL.createObjectURL(blob)
  link.href = blobUrl
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}
