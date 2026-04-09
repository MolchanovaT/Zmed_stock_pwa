import client from './client'

/**
 * Авторизация: отправляем form-data (OAuth2PasswordRequestForm).
 * Возвращает { access_token, token_type }.
 */
export async function login(username, password) {
  const form = new URLSearchParams()
  form.append('username', username)
  form.append('password', password)

  const { data } = await client.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return data
}

/**
 * Данные текущего пользователя.
 * Возвращает { id, username }.
 */
export async function getMe() {
  const { data } = await client.get('/auth/me')
  return data
}
