import { useState, useEffect } from 'react'
import { getLpuList } from '../api/stock'

// Конвертация YYYY-MM-DD → ДД.ММ.ГГГГ для отправки на бэкенд
function toRuDate(isoDate) {
  if (!isoDate) return ''
  const [y, m, d] = isoDate.split('-')
  return `${d}.${m}.${y}`
}

/**
 * Форма оформления заказа.
 *
 * Props:
 *   onSubmit({ lpu, delivery_date, delivery_time, doctor, instrument }) — callback
 *   submitting — boolean, блокирует форму во время отправки
 */
export default function OrderForm({ onSubmit, submitting, initialLpu = '', regionContext = '' }) {
  const [form, setForm] = useState({
    lpu: '',
    lpu_manual: '',
    delivery_date: '',
    delivery_time: '',
    doctor: '',
    instrument: 'нет',
  })
  const [errors, setErrors] = useState({})
  const [lpuList, setLpuList] = useState([])
  const [lpuLoading, setLpuLoading] = useState(true)

  useEffect(() => {
    getLpuList().then((items) => {
      setLpuList(items)
      if (initialLpu) {
        if (items.includes(initialLpu)) {
          setForm((f) => ({ ...f, lpu: initialLpu }))
        } else {
          setForm((f) => ({ ...f, lpu: '__manual__', lpu_manual: initialLpu }))
        }
      }
    }).finally(() => setLpuLoading(false))
  }, [initialLpu])

  const isManual = form.lpu === '__manual__'
  const effectiveLpu = isManual ? form.lpu_manual.trim() : form.lpu

  const validate = () => {
    const e = {}
    if (!effectiveLpu)
      e.lpu = 'Укажите ЛПУ'
    if (!form.delivery_date)
      e.delivery_date = 'Укажите дату доставки'
    if (!/^\d{2}:\d{2}$/.test(form.delivery_time))
      e.delivery_time = 'Введите время в формате ЧЧ:ММ'
    if (!form.doctor.trim())
      e.doctor = 'Укажите врача'
    return e
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length) {
      setErrors(errs)
      return
    }
    setErrors({})
    onSubmit({
      lpu: effectiveLpu,
      delivery_date: toRuDate(form.delivery_date),
      delivery_time: form.delivery_time,
      doctor: form.doctor.trim(),
      instrument: form.instrument,
    })
  }

  const inputClass = (name) =>
    `w-full border rounded-md px-3 py-2 text-sm
     focus:outline-none focus:ring-2 focus:ring-brand-500
     ${errors[name] ? 'border-red-400' : 'border-gray-300'}`

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <h3 className="font-bold text-brand-600 text-sm uppercase tracking-wide">
        Оформление заказа
      </h3>

      {/* Контекст региона — если склад не был выбран конкретно */}
      {regionContext && !initialLpu && (
        <div className="bg-blue-50 border border-blue-100 rounded-md px-3 py-2 text-xs text-blue-700">
          Регион поиска: <span className="font-semibold">{regionContext}</span> — уточните ЛПУ ниже
        </div>
      )}

      {/* ЛПУ — выпадающий список */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          ЛПУ{initialLpu && <span className="ml-1 normal-case font-normal text-green-600">(подставлено из фильтра)</span>}
        </label>
        <select
          value={form.lpu}
          onChange={(e) => setForm((f) => ({ ...f, lpu: e.target.value, lpu_manual: '' }))}
          disabled={submitting || lpuLoading}
          className={inputClass('lpu')}
        >
          <option value="">
            {lpuLoading ? 'Загрузка...' : '— выберите ЛПУ —'}
          </option>
          {lpuList.map((lpu) => (
            <option key={lpu} value={lpu}>{lpu}</option>
          ))}
          <option value="__manual__">✏️ Ввести вручную</option>
        </select>
        {errors.lpu && <p className="text-xs text-red-500 mt-0.5">{errors.lpu}</p>}
      </div>

      {/* Поле ручного ввода ЛПУ */}
      {isManual && (
        <div>
          <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
            Название ЛПУ
          </label>
          <input
            type="text"
            value={form.lpu_manual}
            onChange={(e) => setForm((f) => ({ ...f, lpu_manual: e.target.value }))}
            placeholder="Введите название ЛПУ"
            disabled={submitting}
            className={inputClass('lpu')}
            autoFocus
          />
        </div>
      )}

      {/* Дата доставки — нативный календарь */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Дата доставки
        </label>
        <input
          type="date"
          value={form.delivery_date}
          min={new Date().toISOString().split('T')[0]}
          onChange={(e) => setForm((f) => ({ ...f, delivery_date: e.target.value }))}
          disabled={submitting}
          className={inputClass('delivery_date')}
        />
        {errors.delivery_date && (
          <p className="text-xs text-red-500 mt-0.5">{errors.delivery_date}</p>
        )}
      </div>

      {/* Время доставки — текстовое поле с маской ЧЧ:ММ */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Время доставки
        </label>
        <input
          type="text"
          inputMode="numeric"
          value={form.delivery_time}
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, '').slice(0, 4)
            const masked = digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits
            setForm((f) => ({ ...f, delivery_time: masked }))
          }}
          placeholder="10:00"
          maxLength={5}
          disabled={submitting}
          className={inputClass('delivery_time')}
        />
        {errors.delivery_time && (
          <p className="text-xs text-red-500 mt-0.5">{errors.delivery_time}</p>
        )}
      </div>

      {/* Врач */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Врач (контактное лицо)
        </label>
        <input
          type="text"
          value={form.doctor}
          onChange={(e) => setForm((f) => ({ ...f, doctor: e.target.value }))}
          placeholder="Иванов И.И."
          disabled={submitting}
          className={inputClass('doctor')}
        />
        {errors.doctor && <p className="text-xs text-red-500 mt-0.5">{errors.doctor}</p>}
      </div>

      {/* Инструмент — переключатель */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Нужен инструмент?
        </label>
        <div className="flex gap-2">
          {['нет', 'да'].map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => setForm((f) => ({ ...f, instrument: opt }))}
              className={`px-4 py-1.5 rounded-full text-sm font-medium border transition-colors
                ${form.instrument === opt
                  ? 'bg-brand-500 text-white border-brand-500'
                  : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'
                }`}
            >
              {opt === 'да' ? '✅ Да' : '❌ Нет'}
            </button>
          ))}
        </div>
      </div>

      <button
        type="submit"
        disabled={submitting}
        className="w-full bg-brand-500 hover:bg-brand-600 disabled:opacity-50
                   text-white font-semibold py-2.5 rounded-lg transition-colors"
      >
        {submitting ? 'Отправка...' : '📤 Оформить заказ'}
      </button>
    </form>
  )
}
