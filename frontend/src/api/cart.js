import client from './client'

/** Текущая активная корзина. Возвращает { cart } или { cart: null }. */
export const getCart = () =>
  client.get('/cart').then((r) => r.data.cart)

/**
 * Добавить позицию в корзину.
 * @param {{ article, nomenclature, characteristic, quantity, available_balance, lpu }} item
 */
export const addItem = (item) =>
  client.post('/cart/items', item).then((r) => r.data.cart)

/**
 * Изменить количество позиции.
 * @param {number} itemId
 * @param {number} quantity
 */
export const updateItem = (itemId, quantity) =>
  client.patch(`/cart/items/${itemId}`, { quantity }).then((r) => r.data)

/** Удалить позицию из корзины. */
export const deleteItem = (itemId) =>
  client.delete(`/cart/items/${itemId}`)

/** Очистить корзину полностью. */
export const clearCart = () =>
  client.delete('/cart')

/** Список всех оформленных заказов текущего пользователя. */
export const getOrders = () =>
  client.get('/cart/orders').then((r) => r.data.orders)

/**
 * Оформить заказ.
 * @param {{ delivery_date, delivery_time, doctor, instrument }} order
 */
export const placeOrder = (order) =>
  client.post('/cart/order', order).then((r) => r.data)
