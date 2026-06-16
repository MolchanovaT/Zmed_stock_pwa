import client from './client'

/**
 * Все эндпоинты корзины параметризованы по kind:
 *   'implants' — корзина имплантов (по умолчанию)
 *   'supplies' — корзина расходников
 * У одного пользователя может быть одновременно активная корзина каждого типа.
 */

/** Текущая активная корзина указанного типа. Возвращает объект корзины или null. */
export const getCart = (kind = 'implants') =>
  client.get('/cart', { params: { kind } }).then((r) => r.data.cart)

/**
 * Добавить позицию в корзину.
 * @param {{ article, nomenclature, characteristic, quantity, available_balance, lpu }} item
 * @param {string} kind
 */
export const addItem = (item, kind = 'implants') =>
  client.post('/cart/items', item, { params: { kind } }).then((r) => r.data.cart)

/**
 * Изменить количество позиции (kind не нужен — item_id однозначен).
 */
export const updateItem = (itemId, quantity) =>
  client.patch(`/cart/items/${itemId}`, { quantity }).then((r) => r.data)

/** Удалить позицию из корзины (kind не нужен — item_id однозначен). */
export const deleteItem = (itemId) =>
  client.delete(`/cart/items/${itemId}`)

/** Очистить корзину указанного типа. */
export const clearCart = (kind = 'implants') =>
  client.delete('/cart', { params: { kind } })

/**
 * Список оформленных заказов.
 * @param {string|null} kind — если null/undefined, вернутся заказы всех типов.
 */
export const getOrders = (kind) => {
  const params = kind ? { kind } : {}
  return client.get('/cart/orders', { params }).then((r) => r.data.orders)
}

/**
 * Оформить заказ.
 * @param {{ delivery_date, delivery_time, doctor, instrument, lpu, comment }} order
 * @param {string} kind
 */
export const placeOrder = (order, kind = 'implants') =>
  client.post('/cart/order', order, { params: { kind } }).then((r) => r.data)
