import client from './client'

/* Локации */
export const listLocations = () =>
  client.get('/clinic-stock/locations').then((r) => r.data.locations)

export const createLocation = (body) =>
  client.post('/clinic-stock/locations', body).then((r) => r.data)

export const patchLocation = (id, body) =>
  client.patch(`/clinic-stock/locations/${id}`, body).then((r) => r.data)

/* Товар — пагинируем: {items, total, limit, offset} */
export const listItems = (params = {}) =>
  client.get('/clinic-stock/items', { params }).then((r) => r.data)

export const getItem = (id) =>
  client.get(`/clinic-stock/items/${id}`).then((r) => r.data)

export const scanBarcode = (barcode) =>
  client.get('/clinic-stock/scan', { params: { barcode } }).then((r) => r.data.items)

/* Движения */
export const receive = (body) =>
  client.post('/clinic-stock/receive', body).then((r) => r.data)

export const transfer = (body) =>
  client.post('/clinic-stock/transfer', body).then((r) => r.data)

export const consume = (body) =>
  client.post('/clinic-stock/consume', body).then((r) => r.data)

export const returnItem = (body) =>
  client.post('/clinic-stock/return', body).then((r) => r.data)

export const inventory = (body) =>
  client.post('/clinic-stock/inventory', body).then((r) => r.data)

export const writeOff = (body) =>
  client.post('/clinic-stock/write-off', body).then((r) => r.data)

export const listMovements = (params = {}) =>
  client.get('/clinic-stock/movements', { params }).then((r) => r.data.movements)

/** XLSX журнала движений (blob'ом с JWT). */
export const downloadMovementsXlsx = async (params = {}) => {
  const resp = await client.get('/clinic-stock/movements.xlsx', {
    params, responseType: 'blob', timeout: 120000,
  })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `clinic_stock_movements_${new Date().toISOString().slice(0, 10)}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export const listLosses = (params = {}) =>
  client.get('/clinic-stock/losses', { params }).then((r) => r.data.movements)

export const listOrganizationsForLosses = () =>
  client.get('/clinic-stock/organizations-list').then((r) => r.data.organizations)

/** Открыть XLSX-экспорт потерь (blob'ом с JWT). */
export const downloadLossesXlsx = async (params = {}) => {
  const resp = await client.get('/clinic-stock/losses.xlsx', {
    params, responseType: 'blob',
  })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `clinic_losses_${new Date().toISOString().slice(0, 10)}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
