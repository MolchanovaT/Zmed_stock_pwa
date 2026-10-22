import client from './client'

export const getMonthly = (months = 12) =>
  client.get('/clinic-analytics/monthly', { params: { months } })
    .then((r) => r.data.series)

export const getByClinic = (params = {}) =>
  client.get('/clinic-analytics/by-clinic', { params })
    .then((r) => r.data.items)

export const getTopOperationTypes = (params = {}) =>
  client.get('/clinic-analytics/top-operation-types', { params })
    .then((r) => r.data.items)
