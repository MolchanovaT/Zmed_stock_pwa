import client from './client'

/**
 * Проверить ИНН контрагента.
 * @param {string} inn
 * @param {'diler'|'lpu'} orgType
 * @returns {{ status, name, date }}
 */
export const checkInn = (inn, orgType) =>
  client.post('/inn-check/check', { inn, org_type: orgType }).then((r) => r.data)

/** Добавить заявку на рассмотрение. */
export const addPending = (name, inn) =>
  client.post('/inn-check/pending/add', { name, inn }).then((r) => r.data)
