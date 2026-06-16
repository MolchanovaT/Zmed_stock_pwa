import { useState } from 'react'

export default function OrderCard({ order }) {
  const [open, setOpen] = useState(false)

  const groups = Object.values(
    order.items.reduce((acc, item) => {
      const key = item.nomenclature
      if (!acc[key]) acc[key] = { nomenclature: item.nomenclature, items: [] }
      acc[key].items.push(item)
      return acc
    }, {})
  )

  const createdAt = order.created_at
    ? new Date(order.created_at).toLocaleString('ru-RU', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '—'

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full text-left px-4 py-3 flex items-start justify-between gap-3 hover:bg-gray-50 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-bold text-gray-800">Заказ #{order.id}</span>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full">
              Оформлен
            </span>
            {order.kind === 'supplies' && (
              <span className="text-xs bg-teal-100 text-teal-700 px-2 py-0.5 rounded-full">
                Инструменты
              </span>
            )}
            {order.kind === 'implants' && (
              <span className="text-xs bg-brand-100 text-brand-700 px-2 py-0.5 rounded-full">
                Импланты
              </span>
            )}
          </div>
          <div className="mt-1 text-sm text-gray-500 space-y-0.5">
            <p>📅 Создан: {createdAt}</p>
            {order.source_lpu && (
              <p>🏭 Склад отбора: <span className="font-medium text-gray-700">{order.source_lpu}</span></p>
            )}
            <p>🏥 ЛПУ-получатель: <span className="font-medium text-gray-700">{order.lpu || '—'}</span></p>
            {order.doctor && <p>👨‍⚕️ Врач: <span className="font-medium text-gray-700">{order.doctor}</span></p>}
            {order.delivery_date && (
              <p>🚚 Доставка: <span className="font-medium text-gray-700">{order.delivery_date} в {order.delivery_time}</span></p>
            )}
            {order.comment && (
              <p>💬 Комментарий: <span className="font-medium text-gray-700">{order.comment}</span></p>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-sm text-gray-400">{order.items.length} поз.</p>
          <p className="text-lg mt-1">{open ? '▲' : '▼'}</p>
        </div>
      </button>

      {open && (
        <div className="border-t border-gray-100">
          {groups.map((group) => (
            <div key={group.nomenclature}>
              <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
                <p className="text-sm font-semibold text-gray-800">{group.nomenclature}</p>
              </div>
              {group.items.map((item) => (
                <div key={item.id}
                     className="flex items-center justify-between px-4 py-2 border-b border-gray-50 last:border-0">
                  <div className="min-w-0">
                    <div className="flex gap-2 items-baseline flex-wrap">
                      {item.article && (
                        <span className="font-mono text-xs text-gray-400">{item.article}</span>
                      )}
                      <span className="text-sm text-gray-600 truncate">{item.characteristic || '—'}</span>
                    </div>
                  </div>
                  <span className="shrink-0 ml-4 text-sm font-semibold text-gray-700">
                    × {item.quantity}
                  </span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
