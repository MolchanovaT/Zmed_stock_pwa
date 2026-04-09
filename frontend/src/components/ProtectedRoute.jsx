import { Navigate } from 'react-router-dom'
import { useAuth } from '../store/auth'

/**
 * Оборачивает маршрут: если пользователь не авторизован — редиректит на /login.
 * Пока идёт проверка токена — показывает заглушку.
 */
export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-brand-500">
        Загрузка...
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return children
}
