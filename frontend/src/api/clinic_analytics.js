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

export const getByDoctor = (params = {}) =>
  client.get('/clinic-analytics/by-doctor', { params })
    .then((r) => r.data.items)

export const getByDepartment = (params = {}) =>
  client.get('/clinic-analytics/by-department', { params })
    .then((r) => r.data.items)

export const getMyActivity = () =>
  client.get('/clinic-analytics/my-activity').then((r) => r.data)
