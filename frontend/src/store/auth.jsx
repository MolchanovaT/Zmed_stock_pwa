import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { getMe } from '../api/auth'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)      // { id, username } | null
  const [loading, setLoading] = useState(true) // true пока проверяем токен

  // При монтировании проверяем сохранённый токен
  useEffect(() => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setLoading(false)
      return
    }
    getMe()
      .then(setUser)
      .catch(() => localStorage.removeItem('access_token'))
      .finally(() => setLoading(false))
  }, [])

  const signin = useCallback((token, userData) => {
    localStorage.setItem('access_token', token)
    setUser(userData)
  }, [])

  const signout = useCallback(() => {
    localStorage.removeItem('access_token')
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, signin, signout }}>
      {children}
    </AuthContext.Provider>
  )
}

/** Хук авторизации. Использовать внутри <AuthProvider>. */
export function useAuth() {
  return useContext(AuthContext)
}
