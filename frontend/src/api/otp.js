import client from './client'

/** Запросить OTP-код на email текущего пользователя. */
export const requestOtp = (purpose) =>
  client.post('/otp/request', { purpose }).then((r) => r.data)

/** Проверить (и погасить) OTP-код. Используется напрямую, если
 * действие не поддерживает otp_code в теле основного запроса. */
export const verifyOtp = (purpose, code) =>
  client.post('/otp/verify', { purpose, code }).then((r) => r.data)
