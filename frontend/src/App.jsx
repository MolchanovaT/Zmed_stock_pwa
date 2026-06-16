import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './store/auth'
import ProtectedRoute from './components/ProtectedRoute'
import LoginPage from './pages/LoginPage'
import HomePage from './pages/HomePage'
import SearchPage from './pages/SearchPage'
import CartPage from './pages/CartPage'
import OrdersPage from './pages/OrdersPage'
import SuppliesPage from './pages/SuppliesPage'
import ImplantsViewPage from './pages/ImplantsViewPage'
import InnCheckPage from './pages/InnCheckPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

          {/* Главная — дашборд со списком модулей */}
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <HomePage />
              </ProtectedRoute>
            }
          />

          {/* Модуль: Импланты (с корзиной и заказами) */}
          <Route
            path="/"
            element={
              <ProtectedRoute requiredModule="implants">
                <SearchPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/cart"
            element={
              <ProtectedRoute requiredModule="implants">
                <CartPage kind="implants" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders"
            element={
              <ProtectedRoute requiredModule="implants">
                <OrdersPage kind="implants" />
              </ProtectedRoute>
            }
          />

          {/* Модуль: Импланты — только просмотр (без корзины) */}
          <Route
            path="/implants-view"
            element={
              <ProtectedRoute requiredModule="implants_view">
                <ImplantsViewPage />
              </ProtectedRoute>
            }
          />

          {/* Модуль: Расходники и инструменты (с корзиной и заказами) */}
          <Route
            path="/supplies"
            element={
              <ProtectedRoute requiredModule="supplies">
                <SuppliesPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/supplies/cart"
            element={
              <ProtectedRoute requiredModule="supplies">
                <CartPage kind="supplies" />
              </ProtectedRoute>
            }
          />
          <Route
            path="/supplies/orders"
            element={
              <ProtectedRoute requiredModule="supplies">
                <OrdersPage kind="supplies" />
              </ProtectedRoute>
            }
          />

          {/* Модуль: Проверка контрагентов по ИНН */}
          <Route
            path="/inn-check"
            element={
              <ProtectedRoute requiredModule="inn_check">
                <InnCheckPage />
              </ProtectedRoute>
            }
          />

          {/* Любой неизвестный маршрут → на главную */}
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
