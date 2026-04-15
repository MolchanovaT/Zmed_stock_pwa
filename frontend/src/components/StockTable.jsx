/**
 * Список остатков в виде карточек с пагинацией.
 *
 * Props:
 *   result      — { items, total, page, total_pages, updated_at }
 *   loading     — boolean
 *   page        — текущая страница (controlled)
 *   onPageChange(n) — смена страницы
 *   onAddToCart(item) — добавить строку в корзину
 */
export default function StockTable({ result, loading, page, onPageChange, onAddToCart }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Поиск...
      </div>
    )
  }

  if (!result) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-300 text-sm">
        Выберите фильтры слева для отображения остатков
      </div>
    )
  }

  const { items, total, total_pages, updated_at } = result

  if (items.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400 text-sm">
        Ничего не найдено
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Заголовок с датой актуальности */}
      <div className="flex items-center justify-between mb-2 text-xs text-gray-500">
        <span>Найдено: <b>{total}</b> позиций</span>
        <span>Актуально на: <b>{updated_at}</b></span>
      </div>

      {/* Карточки */}
      <div className="flex-1 overflow-y-auto space-y-2 pr-0.5">
        {items.map((item, i) => (
          <div
            key={i}
            className="bg-white rounded-lg border border-gray-100 shadow-sm p-3 flex items-start gap-3"
          >
            {/* Основная информация */}
            <div className="flex-1 min-w-0">
              {item.article && (
                <p className="font-mono text-xs text-gray-400 mb-0.5">{item.article}</p>
              )}
              <p className="text-sm font-medium text-gray-800 leading-snug">
                {item.nomenclature}
              </p>
              {item.characteristic && (
                <p className="text-xs text-gray-500 mt-0.5">{item.characteristic}</p>
              )}
              <p className="text-xs text-brand-600 font-semibold mt-1">
                На складе: {item.balance.toLocaleString('ru-RU')} шт.
              </p>
            </div>

            {/* Кнопка добавления — только если передан обработчик */}
            {onAddToCart && (
              <button
                onClick={() => onAddToCart(item)}
                className="shrink-0 bg-brand-500 hover:bg-brand-600 active:bg-brand-700
                           text-white text-xs font-semibold
                           px-3 py-2 rounded-lg transition-colors whitespace-nowrap"
              >
                + В корзину
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Пагинация */}
      {total_pages > 1 && (
        <div className="flex items-center justify-center gap-2 mt-3">
          <button
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="px-3 py-1 text-sm rounded border border-gray-300
                       disabled:opacity-30 hover:bg-gray-50 transition-colors"
          >
            ← Назад
          </button>
          <span className="text-sm text-gray-600">
            Страница {page} из {total_pages}
          </span>
          <button
            disabled={page >= total_pages}
            onClick={() => onPageChange(page + 1)}
            className="px-3 py-1 text-sm rounded border border-gray-300
                       disabled:opacity-30 hover:bg-gray-50 transition-colors"
          >
            Вперёд →
          </button>
        </div>
      )}
    </div>
  )
}
