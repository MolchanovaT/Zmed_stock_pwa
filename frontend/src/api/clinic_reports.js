import client from './client'

/**
 * API-клиент модуля «Отчёты клиник об операциях».
 * ПДн пациента НЕ передаются — только patient_code (обезличенный идентификатор).
 */

export const listReports = (params = {}) =>
  client.get('/clinic-reports', { params }).then((r) => r.data.reports)

export const getReport = (id) =>
  client.get(`/clinic-reports/${id}`).then((r) => r.data)

export const createReport = (body) =>
  client.post('/clinic-reports', body).then((r) => r.data)

export const patchReport = (id, body) =>
  client.patch(`/clinic-reports/${id}`, body).then((r) => r.data)

export const deleteReport = (id) =>
  client.delete(`/clinic-reports/${id}`)

/** Загрузить один файл (image/pdf) к отчёту. */
export const uploadReportFile = (reportId, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post(`/clinic-reports/${reportId}/files`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }).then((r) => r.data)
}

/** Открыть файл отчёта в новой вкладке. Качает blob'ом с JWT (endpoint защищён). */
export const openReportFile = async (reportId, fileId, filename) => {
  const resp = await client.get(`/clinic-reports/${reportId}/files/${fileId}`, {
    responseType: 'blob',
  })
  const blob = resp.data
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  if (filename) a.download = filename
  a.target = '_blank'
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

export const deleteReportFile = (reportId, fileId) =>
  client.delete(`/clinic-reports/${reportId}/files/${fileId}`)

export const suggestDoctors = (q = '') =>
  client.get('/clinic-reports/suggest/doctors', { params: { q } })
    .then((r) => r.data.items)

export const suggestOperationTypes = (q = '') =>
  client.get('/clinic-reports/suggest/operation-types', { params: { q } })
    .then((r) => r.data.items)

/** Скачать XLSX с отчётами (blob'ом, с JWT). */
export const downloadReportsXlsx = async (params = {}) => {
  const resp = await client.get('/clinic-reports/export.xlsx', {
    params, responseType: 'blob',
  })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = `clinic_reports_${new Date().toISOString().slice(0, 10)}.xlsx`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}
