import { useState, useEffect, useMemo } from 'react'
import { getLpuList } from '../api/stock'
import { getSuppliesLpuList } from '../api/supplies'
import SearchableSelect from './SearchableSelect'

const MANUAL_LABEL = '✏️ Ввести вручную'
const CUSTOM_SLOT = '__custom__'

const TIME_SLOT_GROUPS = [
  { label: 'Утро',  slots: ['07:00-08:30', '08:30-10:00', '10:00-11:00'] },
  { label: 'День',  slots: ['11:00-12:00', '12:00-13:00', '13:00-14:00'] },
  { label: 'Вечер', slots: ['14:00-15:00', '15:00-16:00', '16:00-17:00'] },
]

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
 *   onSubmit({ lpu, delivery_date, delivery_time, doctor, instrument, comment }) — callback
 *   submitting — boolean
 *   sourceLpu  — склад-источник (исключается из списка получателей)
 *   regionContext — регион поиска (фильтрует список складов)
 *   kind — 'implants' | 'supplies'; определяет источник списка ЛПУ
 */
export default function OrderForm({ onSubmit, submitting, sourceLpu = '', regionContext = '', kind = 'implants' }) {
  const [form, setForm] = useState({
    lpu: '',
    lpu_manual: '',
    delivery_date: '',
    time_slot: '',          // один из пресетов или CUSTOM_SLOT
    time_custom_from: '',   // HH:MM, только при CUSTOM_SLOT
    time_custom_to: '',     // HH:MM, только при CUSTOM_SLOT
    doctor: '',
    instrument: 'нет',
    comment: '',
  })
  const [errors, setErrors] = useState({})
  const [lpuList, setLpuList] = useState([])
  const [lpuLoading, setLpuLoading] = useState(true)

  useEffect(() => {
    setLpuLoading(true)
    const fetcher = kind === 'supplies' ? getSuppliesLpuList : getLpuList
    fetcher(regionContext)
      .then(setLpuList)
      .finally(() => setLpuLoading(false))
  }, [regionContext, kind])

  // Список получателей = все склады минус источник (case-insensitive)
  const recipientOptions = useMemo(() => {
    const src = (sourceLpu || '').trim().toLowerCase()
    const filtered = src
      ? lpuList.filter((it) => (it || '').trim().toLowerCase() !== src)
      : lpuList
    return [...filtered, MANUAL_LABEL]
  }, [lpuList, sourceLpu])

  const isManual = form.lpu === '__manual__'
  const isCustomTime = form.time_slot === CUSTOM_SLOT
  const effectiveLpu = isManual ? form.lpu_manual.trim() : form.lpu

  const effectiveTime = isCustomTime
    ? (form.time_custom_from && form.time_custom_to
        ? `${form.time_custom_from}-${form.time_custom_to}`
        : '')
    : form.time_slot

  const validate = () => {
    const e = {}
    if (!effectiveLpu) e.lpu = 'Укажите ЛПУ-получатель'
    else if (sourceLpu && effectiveLpu.trim().toLowerCase() === sourceLpu.trim().toLowerCase())
      e.lpu = 'Получатель должен отличаться от склада отбора'
    if (!form.delivery_date) e.delivery_date = 'Укажите дату доставки'
    if (!form.time_slot) e.delivery_time = 'Выберите время доставки'
    else if (isCustomTime) {
      if (!/^\d{2}:\d{2}$/.test(form.time_custom_from) || !/^\d{2}:\d{2}$/.test(form.time_custom_to))
        e.delivery_time = 'Укажите время "с" и "до" в формате ЧЧ:ММ'
      else if (form.time_custom_from >= form.time_custom_to)
        e.delivery_time = 'Время "до" должно быть позже времени "с"'
    }
    if (!form.doctor.trim()) e.doctor = 'Укажите врача'
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
      delivery_time: effectiveTime,
      doctor: form.doctor.trim(),
      instrument: form.instrument,
      comment: form.comment.trim(),
    })
  }

  const inputClass = (name) =>
    `w-full border rounded-md px-3 py-2 text-sm
     focus:outline-none focus:ring-2 focus:ring-brand-500
     ${errors[name] ? 'border-red-400' : 'border-gray-300'}`

  const slotChip = (slot, label) => {
    const active = form.time_slot === slot
    return (
      <button
        key={slot}
        type="button"
        onClick={() => setForm((f) => ({ ...f, time_slot: slot }))}
        disabled={submitting}
        className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors
          ${active
            ? 'bg-brand-500 text-white border-brand-500'
            : 'bg-white text-gray-600 border-gray-300 hover:border-brand-400'}`}
      >
        {label}
      </button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <h3 className="font-bold text-brand-600 text-sm uppercase tracking-wide">
        Оформление заказа
      </h3>

      {/* Контекст: склад отбора и регион */}
      {sourceLpu && (
        <div className="bg-amber-50 border border-amber-200 rounded-md px-3 py-2 text-xs text-amber-800">
          🏭 Склад отбора: <span className="font-semibold">{sourceLpu}</span>
          <span className="block mt-0.5 text-amber-700/80">
            Получатель не может совпадать с этим складом.
          </span>
        </div>
      )}
      {regionContext && !sourceLpu && (
        <div className="bg-blue-50 border border-blue-100 rounded-md px-3 py-2 text-xs text-blue-700">
          Регион поиска: <span className="font-semibold">{regionContext}</span> — уточните ЛПУ ниже
        </div>
      )}

      {/* ЛПУ-получатель */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          ЛПУ-получатель
        </label>
        <SearchableSelect
          value={form.lpu === '__manual__' ? MANUAL_LABEL : form.lpu}
          onChange={(v) => setForm((f) => ({
            ...f,
            lpu: v === MANUAL_LABEL ? '__manual__' : v,
            lpu_manual: '',
          }))}
          options={recipientOptions}
          disabled={submitting}
          isLoading={lpuLoading}
          accent="brand"
        />
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

      {/* Дата доставки */}
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

      {/* Время доставки — слоты */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Время доставки
        </label>
        <div className="space-y-2">
          {TIME_SLOT_GROUPS.map((group) => (
            <div key={group.label}>
              <p className="text-[11px] text-gray-400 mb-1">{group.label}</p>
              <div className="flex flex-wrap gap-1.5">
                {group.slots.map((s) => slotChip(s, s.replace('-', ' – ')))}
              </div>
            </div>
          ))}
          <div>
            <div className="flex flex-wrap gap-1.5">
              {slotChip(CUSTOM_SLOT, '⏱ В течение дня')}
            </div>
            {isCustomTime && (
              <div className="mt-2 flex items-center gap-2 text-sm">
                <span className="text-gray-500">с</span>
                <input
                  type="time"
                  value={form.time_custom_from}
                  onChange={(e) => setForm((f) => ({ ...f, time_custom_from: e.target.value }))}
                  disabled={submitting}
                  className="border border-gray-300 rounded-md px-2 py-1.5 text-sm
                             focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
                <span className="text-gray-500">до</span>
                <input
                  type="time"
                  value={form.time_custom_to}
                  onChange={(e) => setForm((f) => ({ ...f, time_custom_to: e.target.value }))}
                  disabled={submitting}
                  className="border border-gray-300 rounded-md px-2 py-1.5 text-sm
                             focus:outline-none focus:ring-2 focus:ring-brand-500"
                />
              </div>
            )}
          </div>
        </div>
        {errors.delivery_time && (
          <p className="text-xs text-red-500 mt-1">{errors.delivery_time}</p>
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

      {/* Инструмент */}
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

      {/* Комментарии */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 mb-1 uppercase tracking-wide">
          Комментарии <span className="normal-case font-normal text-gray-400">(необязательно)</span>
        </label>
        <textarea
          value={form.comment}
          onChange={(e) => setForm((f) => ({ ...f, comment: e.target.value }))}
          placeholder="Особые пожелания, уточнения по доставке, и т.п."
          rows={3}
          disabled={submitting}
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm
                     focus:outline-none focus:ring-2 focus:ring-brand-500 resize-y"
        />
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
