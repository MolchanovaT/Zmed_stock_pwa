import { Navigate } from 'react-router-dom'
import { useAuth } from '../store/auth'

/**
 * Оборачивает маршрут:
 *   - не авторизован → /login
 *   - нет доступа к модулю → /home (с сообщением)
 *   - всё ок → рендерит children
 *
 * Props:
 *   requiredModule — строка модуля ('implants', 'supplies', …).
 *                    Если не передан — проверяется только авторизация.
 */
export default function ProtectedRoute({ children, requiredModule }) {
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

  if (requiredModule && !user.modules?.includes(requiredModule)) {
    return <Navigate to="/home" replace />
  }

  return children
}
