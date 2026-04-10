import { updateItem, deleteItem } from '../api/cart'

/**
 * Карточка одной позиции в корзине с кнопками +/- и удалением.
 *
 * Props:
 *   item      — объект позиции { id, article, nomenclature, characteristic, quantity, available_balance }
 *   onUpdate(id, newQty) — callback после изменения количества
 *   onDelete(id)         — callback после удаления
 */
export default function CartItem({ item, onUpdate, onDelete, compact = false }) {
  const handleQty = async (delta) => {
    const newQty = item.quantity + delta
    if (newQty < 1) return
    await updateItem(item.id, newQty)
    onUpdate(item.id, newQty)
  }

  const handleDelete = async () => {
    await deleteItem(item.id)
    onDelete(item.id)
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2">
      {/* Информация о позиции */}
      <div className="flex-1 min-w-0">
        {!compact && (
          <p className="text-sm font-medium text-gray-800 leading-snug truncate">
            {item.nomenclature}
          </p>
        )}
        <div className="flex gap-2 items-baseline flex-wrap">
          {item.article && (
            <span className="font-mono text-xs text-gray-400">{item.article}</span>
          )}
          <span className={`truncate ${compact ? 'text-sm text-gray-700' : 'text-xs text-gray-500'}`}>
            {item.characteristic || '—'}
          </span>
        </div>
        <p className="text-xs text-gray-400 mt-0.5">
          На складе: {Math.round(item.available_balance)} шт.
        </p>
      </div>

      {/* Количество */}
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={() => handleQty(-1)}
          disabled={item.quantity <= 1}
          className="w-7 h-7 rounded border border-gray-300 text-gray-600
                     hover:bg-gray-100 disabled:opacity-30 transition-colors text-lg leading-none"
        >
          −
        </button>
        <span className="w-8 text-center text-sm font-semibold">{item.quantity}</span>
        <button
          onClick={() => handleQty(+1)}
          disabled={item.quantity >= Math.round(item.available_balance)}
          className="w-7 h-7 rounded border border-gray-300 text-gray-600
                     hover:bg-gray-100 disabled:opacity-30 transition-colors text-lg leading-none"
        >
          +
        </button>
      </div>

      {/* Удалить */}
      <button
        onClick={handleDelete}
        className="shrink-0 text-red-400 hover:text-red-600 transition-colors text-lg"
        title="Удалить позицию"
      >
        ✕
      </button>
    </div>
  )
}
