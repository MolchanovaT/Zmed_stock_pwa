import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import {
  listItems, listLocations, createLocation,
  receive, transfer, consume, returnItem, inventory, writeOff,
  listMovements,
} from '../api/clinic_stock'
import { listReports } from '../api/clinic_reports'

const MOVE_LABEL = {
  receive: 'Приход', transfer: 'Перемещение', consume: 'Расход',
  return: 'Возврат', inventory_adjust: 'Инвентаризация', write_off: 'Списание',
}
const MOVE_COLOR = {
  receive: 'bg-emerald-100 text-emerald-800',
  transfer: 'bg-sky-100 text-sky-800',
  consume: 'bg-amber-100 text-amber-800',
  return: 'bg-indigo-100 text-indigo-800',
  inventory_adjust: 'bg-purple-100 text-purple-800',
  write_off: 'bg-red-100 text-red-800',
}
const LOC_KIND_LABEL = { warehouse: 'склад', surgery: 'оперблок', other: 'иное' }

/** Проверка срока годности: 1 — просрочен, 0 — ок, -1 — <30 дней. */
function expirationState(dateStr) {
  if (!dateStr) return 0
  const today = new Date()
  const d = new Date(dateStr)
  const diff = Math.round((d - today) / (1000 * 60 * 60 * 24))
  if (diff < 0) return 1
  if (diff < 30) return -1
  return 0
}

/* ── Модалки движений ──────────────────────────────────────────────────── */

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white rounded-xl p-5 w-full max-w-md max-h-[90vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-800">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

function Field({ label, children, hint }) {
  return (
    <div className="mb-3">
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-gray-400 mt-1">{hint}</p>}
    </div>
  )
}

function LocationSelect({ value, onChange, locations, exclude }) {
  return (
    <select value={value} onChange={(e) => onChange(Number(e.target.value) || '')}
            className="w-full border rounded px-3 py-2 text-sm">
      <option value="">— выберите —</option>
      {locations.filter((l) => l.id !== exclude && l.active).map((l) => (
        <option key={l.id} value={l.id}>{l.name} ({LOC_KIND_LABEL[l.kind]})</option>
      ))}
    </select>
  )
}

/* ── Главная страница ──────────────────────────────────────────────────── */

export default function ClinicStockPage() {
  const { user, signout } = useAuth()
  const navigate = useNavigate()

  const [tab, setTab] = useState('balances')
  const [items, setItems] = useState([])
  const [locations, setLocations] = useState([])
  const [movements, setMovements] = useState([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [modal, setModal] = useState(null)  // {kind: 'receive'|..., item?}
  const [newLocation, setNewLocation] = useState({ name: '', kind: 'warehouse' })

  const [itemsTotal, setItemsTotal] = useState(0)
  const [itemsOffset, setItemsOffset] = useState(0)
  const PAGE_SIZE = 100

  const refresh = async (append = false) => {
    setLoading(true)
    const nextOffset = append ? itemsOffset + PAGE_SIZE : 0
    try {
      const [itemsResp, locs] = await Promise.all([
        listItems({ q: search || undefined, limit: PAGE_SIZE, offset: nextOffset }),
        listLocations(),
      ])
      setItems((prev) => append ? [...prev, ...itemsResp.items] : itemsResp.items)
      setItemsTotal(itemsResp.total || 0)
      setItemsOffset(nextOffset)
      setLocations(locs)
      setError('')
      if (tab === 'movements') {
        const mv = await listMovements({ limit: 500 })
        setMovements(mv)
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() /* eslint-disable-line */ }, [tab])

  const locMap = useMemo(() => Object.fromEntries(locations.map((l) => [l.id, l])), [locations])

  const addLocation = async () => {
    if (!newLocation.name.trim()) return
    try {
      await createLocation(newLocation)
      setNewLocation({ name: '', kind: 'warehouse' })
      refresh()
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка создания локации')
    }
  }

  const openModal = (kind, item = null) => {
    if (['transfer', 'consume', 'return', 'write_off', 'inventory'].includes(kind) && !item) {
      setError('Выберите партию в таблице')
      return
    }
    setModal({ kind, item })
    setError('')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/home')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← Разделы</button>
          <span className="text-xl ml-3">📦</span>
          <span className="font-bold text-gray-800">Учёт на ОХ</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">{user?.username}</span>
          <button onClick={signout}
                  className="text-sm text-gray-400 hover:text-red-500">Выйти</button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-5">
        {/* Табы */}
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setTab('balances')}
                  className={`px-4 py-2 rounded-lg text-sm font-medium ${
                    tab === 'balances' ? 'bg-amber-600 text-white' : 'bg-white border'
                  }`}>Остатки</button>
          <button onClick={() => setTab('movements')}
                  className={`px-4 py-2 rounded-lg text-sm font-medium ${
                    tab === 'movements' ? 'bg-amber-600 text-white' : 'bg-white border'
                  }`}>Журнал</button>
          <button onClick={() => setTab('locations')}
                  className={`px-4 py-2 rounded-lg text-sm font-medium ${
                    tab === 'locations' ? 'bg-amber-600 text-white' : 'bg-white border'
                  }`}>Локации</button>

          <div className="ml-auto flex gap-2 flex-wrap">
            <button onClick={() => navigate('/clinic-stock/losses')}
                    className="bg-rose-600 hover:bg-rose-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              🚨 Потери
            </button>
            <button onClick={() => navigate('/clinic-stock/scan')}
                    className="bg-sky-600 hover:bg-sky-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              📷 Сканировать
            </button>
            <button onClick={() => openModal('receive')}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              + Приход
            </button>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 text-red-700 rounded p-3 text-sm">{error}</div>
        )}

        {/* ── Вкладка «Остатки» ───────────────────────────────────────── */}
        {tab === 'balances' && (
          <>
            <div className="flex gap-2">
              <input value={search} onChange={(e) => setSearch(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && refresh()}
                     placeholder="Поиск: артикул, номенклатура, lot, штрихкод"
                     className="flex-1 border rounded px-3 py-2 text-sm"/>
              <button onClick={refresh}
                      className="bg-gray-800 text-white rounded px-4 text-sm">Найти</button>
            </div>

            {loading ? <div className="text-center text-gray-400 py-10">Загрузка…</div>
             : items.length === 0 ? (
              <div className="text-center text-gray-400 py-16">
                <div className="text-5xl mb-3">📭</div>
                <p>На ОХ пока ничего нет. Начните с «+ Приход».</p>
              </div>
             ) : (
              <div className="bg-white rounded-xl border overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-xs text-gray-500">
                    <tr>
                      <th className="text-left p-2">Партия</th>
                      <th className="text-left p-2">Lot</th>
                      <th className="text-left p-2">Срок</th>
                      <th className="text-left p-2">Остатки по локациям</th>
                      <th className="text-right p-2">Всего</th>
                      <th className="p-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => {
                      const expState = expirationState(it.expiration_date)
                      return (
                        <tr key={it.id} className="border-t">
                          <td className="p-2">
                            <div className="font-medium text-gray-800">{it.article}</div>
                            <div className="text-xs text-gray-500">{it.nomenclature}</div>
                            {it.characteristic && (
                              <div className="text-xs text-gray-400">{it.characteristic}</div>
                            )}
                          </td>
                          <td className="p-2 text-gray-700">{it.lot_number || '—'}</td>
                          <td className="p-2">
                            <span className={
                              expState === 1 ? 'text-red-600 font-medium' :
                              expState === -1 ? 'text-amber-600' : 'text-gray-700'
                            }>
                              {it.expiration_date || '—'}
                              {expState === 1 && ' ⚠️'}
                            </span>
                          </td>
                          <td className="p-2">
                            <div className="space-y-0.5">
                              {it.balances.length === 0 ? <span className="text-gray-400">—</span>
                               : it.balances.map((b) => (
                                <div key={b.location_id} className="text-xs">
                                  <span className="text-gray-500">{b.location_name}:</span>
                                  <span className={`ml-1 font-medium ${b.quantity > 0 ? 'text-gray-800' : 'text-gray-400'}`}>
                                    {b.quantity}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </td>
                          <td className="p-2 text-right font-semibold">
                            {it.total_balance}
                          </td>
                          <td className="p-2 whitespace-nowrap text-right">
                            <button onClick={() => openModal('transfer', it)}
                                    className="text-sky-600 hover:text-sky-800 text-xs mr-2">⇄</button>
                            <button onClick={() => openModal('consume', it)}
                                    className="text-amber-600 hover:text-amber-800 text-xs mr-2">✓</button>
                            <button onClick={() => openModal('return', it)}
                                    className="text-indigo-600 hover:text-indigo-800 text-xs mr-2">↶</button>
                            <button onClick={() => openModal('inventory', it)}
                                    className="text-purple-600 hover:text-purple-800 text-xs mr-2">📋</button>
                            <button onClick={() => openModal('write_off', it)}
                                    className="text-red-600 hover:text-red-800 text-xs">🗑</button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <div className="text-xs text-gray-400 p-2 border-t flex items-center justify-between gap-2 flex-wrap">
                  <span>⇄ переместить · ✓ расход на операцию · ↶ возврат · 📋 инвентаризация · 🗑 списание</span>
                  <span>показано {items.length} из {itemsTotal}</span>
                </div>
              </div>
             )}
            {items.length > 0 && items.length < itemsTotal && (
              <button onClick={() => refresh(true)} disabled={loading}
                      className="mx-auto block mt-3 bg-white border border-amber-500 text-amber-700 hover:bg-amber-50 rounded-lg px-5 py-2 text-sm font-medium disabled:opacity-50">
                {loading ? 'Загрузка…' : `Загрузить ещё (${itemsTotal - items.length})`}
              </button>
            )}
          </>
        )}

        {/* ── Вкладка «Журнал» ────────────────────────────────────────── */}
        {tab === 'movements' && (
          <div className="bg-white rounded-xl border overflow-x-auto">
            {loading ? <div className="text-center text-gray-400 py-10">Загрузка…</div>
             : movements.length === 0 ? (
              <div className="text-center text-gray-400 py-10">Движений пока нет</div>
             ) : (
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="text-left p-2">Когда</th>
                    <th className="text-left p-2">Тип</th>
                    <th className="text-left p-2">Партия</th>
                    <th className="text-left p-2">Откуда → Куда</th>
                    <th className="text-right p-2">Кол-во</th>
                    <th className="text-left p-2">Отчёт</th>
                    <th className="text-left p-2">Заметка</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.map((m) => {
                    const it = items.find((x) => x.id === m.item_id)
                    const fromL = locMap[m.from_location_id]
                    const toL = locMap[m.to_location_id]
                    return (
                      <tr key={m.id} className="border-t">
                        <td className="p-2 text-xs text-gray-500">
                          {m.created_at ? new Date(m.created_at).toLocaleString() : '—'}
                        </td>
                        <td className="p-2">
                          <span className={`${MOVE_COLOR[m.kind]} text-xs px-2 py-0.5 rounded-full font-medium`}>
                            {MOVE_LABEL[m.kind] || m.kind}
                          </span>
                        </td>
                        <td className="p-2 text-xs">
                          {it ? <>{it.article}<br/><span className="text-gray-400">{it.nomenclature}</span></>
                              : `#${m.item_id}`}
                        </td>
                        <td className="p-2 text-xs text-gray-600">
                          {fromL?.name || '—'} → {toL?.name || '—'}
                        </td>
                        <td className="p-2 text-right font-medium">
                          {m.quantity > 0 ? '+' : ''}{m.quantity}
                        </td>
                        <td className="p-2 text-xs">
                          {m.operation_report_id
                            ? <a href={`/clinic-reports/${m.operation_report_id}`}
                                 className="text-brand-600 hover:underline">
                                #{m.operation_report_id}
                              </a>
                            : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="p-2 text-xs text-gray-500 max-w-xs truncate">
                          {m.note || ''}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
             )}
          </div>
        )}

        {/* ── Вкладка «Локации» ───────────────────────────────────────── */}
        {tab === 'locations' && (
          <div className="bg-white rounded-xl border p-4">
            <div className="mb-4">
              <h3 className="font-semibold text-gray-800 mb-2">+ Новая локация</h3>
              <div className="flex gap-2 flex-wrap">
                <input value={newLocation.name}
                       onChange={(e) => setNewLocation({ ...newLocation, name: e.target.value })}
                       placeholder="Напр.: Склад больницы, Операционная №3"
                       className="flex-1 min-w-[180px] border rounded px-3 py-2 text-sm"/>
                <select value={newLocation.kind}
                        onChange={(e) => setNewLocation({ ...newLocation, kind: e.target.value })}
                        className="border rounded px-3 py-2 text-sm">
                  <option value="warehouse">склад</option>
                  <option value="surgery">оперблок</option>
                  <option value="other">иное</option>
                </select>
                <button onClick={addLocation}
                        className="bg-emerald-600 text-white rounded px-4 py-2 text-sm font-medium">
                  Добавить
                </button>
              </div>
            </div>

            <h3 className="font-semibold text-gray-800 mb-2">Существующие локации</h3>
            {locations.length === 0 ? (
              <p className="text-sm text-gray-400">Пока нет — добавьте хотя бы «Склад больницы» и «Операционный блок».</p>
            ) : (
              <ul className="divide-y">
                {locations.map((l) => (
                  <li key={l.id} className="py-2 flex items-center justify-between">
                    <div>
                      <div className="font-medium text-gray-800">{l.name}</div>
                      <div className="text-xs text-gray-500">{LOC_KIND_LABEL[l.kind]}{!l.active && ' · неактивна'}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </main>

      {/* Модалки */}
      {modal?.kind === 'receive' && (
        <ReceiveModal locations={locations}
                      onClose={() => setModal(null)}
                      onDone={() => { setModal(null); refresh() }}/>
      )}
      {modal?.kind === 'transfer' && (
        <TransferModal item={modal.item} locations={locations}
                        onClose={() => setModal(null)}
                        onDone={() => { setModal(null); refresh() }}/>
      )}
      {modal?.kind === 'consume' && (
        <ConsumeModal item={modal.item} locations={locations}
                      onClose={() => setModal(null)}
                      onDone={() => { setModal(null); refresh() }}/>
      )}
      {modal?.kind === 'return' && (
        <ReturnModal item={modal.item} locations={locations}
                     onClose={() => setModal(null)}
                     onDone={() => { setModal(null); refresh() }}/>
      )}
      {modal?.kind === 'inventory' && (
        <InventoryModal item={modal.item} locations={locations}
                        onClose={() => setModal(null)}
                        onDone={() => { setModal(null); refresh() }}/>
      )}
      {modal?.kind === 'write_off' && (
        <WriteOffModal item={modal.item} locations={locations}
                       onClose={() => setModal(null)}
                       onDone={() => { setModal(null); refresh() }}/>
      )}
    </div>
  )
}

/* ── Формы движений ────────────────────────────────────────────────────── */

function ReceiveModal({ locations, onClose, onDone }) {
  const [form, setForm] = useState({
    article: '', nomenclature: '', characteristic: '',
    lot_number: '', expiration_date: '', barcode: '',
    to_location_id: '', quantity: 1, doc_number: '', note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      await receive({ ...form, quantity: Number(form.quantity),
                      to_location_id: Number(form.to_location_id) })
      onDone()
    } catch (e) {
      setErr(e.response?.data?.detail || 'Ошибка')
    } finally { setBusy(false) }
  }

  return (
    <Modal title="📦 Приход от ZMed" onClose={onClose}>
      {err && <div className="bg-red-50 text-red-700 rounded p-2 text-sm mb-2">{err}</div>}
      <Field label="Артикул *">
        <input value={form.article} onChange={(e) => setForm({ ...form, article: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Номенклатура *">
        <input value={form.nomenclature} onChange={(e) => setForm({ ...form, nomenclature: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Характеристика">
        <input value={form.characteristic} onChange={(e) => setForm({ ...form, characteristic: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Lot №">
          <input value={form.lot_number} onChange={(e) => setForm({ ...form, lot_number: e.target.value })}
                 className="w-full border rounded px-3 py-2 text-sm"/>
        </Field>
        <Field label="Срок годности">
          <input type="date" value={form.expiration_date}
                 onChange={(e) => setForm({ ...form, expiration_date: e.target.value })}
                 className="w-full border rounded px-3 py-2 text-sm"/>
        </Field>
      </div>
      <Field label="Штрихкод">
        <input value={form.barcode} onChange={(e) => setForm({ ...form, barcode: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Куда (локация) *">
        <LocationSelect value={form.to_location_id} locations={locations}
                        onChange={(v) => setForm({ ...form, to_location_id: v })}/>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Количество *">
          <input type="number" min={1} value={form.quantity}
                 onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                 className="w-full border rounded px-3 py-2 text-sm"/>
        </Field>
        <Field label="Номер документа">
          <input value={form.doc_number} onChange={(e) => setForm({ ...form, doc_number: e.target.value })}
                 className="w-full border rounded px-3 py-2 text-sm"/>
        </Field>
      </div>
      <Field label="Заметка">
        <textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
                  rows={2} className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy}
              className="w-full bg-emerald-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Оприходовать'}
      </button>
    </Modal>
  )
}

function TransferModal({ item, locations, onClose, onDone }) {
  const [form, setForm] = useState({
    from_location_id: item.balances.find((b) => b.quantity > 0)?.location_id || '',
    to_location_id: '',
    quantity: 1, doc_number: '', note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      await transfer({ item_id: item.id, ...form,
                       from_location_id: Number(form.from_location_id),
                       to_location_id: Number(form.to_location_id),
                       quantity: Number(form.quantity) })
      onDone()
    } catch (e) { setErr(e.response?.data?.detail || 'Ошибка') }
    finally { setBusy(false) }
  }

  return (
    <Modal title={`⇄ Переместить · ${item.article}`} onClose={onClose}>
      {err && <div className="bg-red-50 text-red-700 rounded p-2 text-sm mb-2">{err}</div>}
      <Field label="Откуда *">
        <LocationSelect value={form.from_location_id} locations={locations}
                        exclude={form.to_location_id}
                        onChange={(v) => setForm({ ...form, from_location_id: v })}/>
      </Field>
      <Field label="Куда *">
        <LocationSelect value={form.to_location_id} locations={locations}
                        exclude={form.from_location_id}
                        onChange={(v) => setForm({ ...form, to_location_id: v })}/>
      </Field>
      <Field label="Количество *">
        <input type="number" min={1} value={form.quantity}
               onChange={(e) => setForm({ ...form, quantity: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Номер документа / заметка">
        <input value={form.doc_number} onChange={(e) => setForm({ ...form, doc_number: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy}
              className="w-full bg-sky-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Переместить'}
      </button>
    </Modal>
  )
}

function ConsumeModal({ item, locations, onClose, onDone }) {
  const [form, setForm] = useState({
    from_location_id: item.balances.find((b) => b.quantity > 0)?.location_id || '',
    quantity: 1, operation_report_id: '', doc_number: '', note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [reports, setReports] = useState([])

  useEffect(() => {
    listReports({ status: 'submitted', limit: 50 })
      .then((data) => setReports(data?.reports || []))
      .catch(() => {})
  }, [])

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      await consume({ item_id: item.id, ...form,
                      from_location_id: Number(form.from_location_id),
                      quantity: Number(form.quantity),
                      operation_report_id: form.operation_report_id
                        ? Number(form.operation_report_id) : null })
      onDone()
    } catch (e) { setErr(e.response?.data?.detail || 'Ошибка') }
    finally { setBusy(false) }
  }

  const expState = expirationState(item.expiration_date)

  return (
    <Modal title={`✓ Расход на операцию · ${item.article}`} onClose={onClose}>
      {err && <div className="bg-red-50 text-red-700 rounded p-2 text-sm mb-2">{err}</div>}
      {expState === 1 && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded p-2 text-xs mb-3">
          ⚠️ У партии истёк срок годности ({item.expiration_date}). Можно расходовать с подтверждением.
        </div>
      )}
      <Field label="Откуда *">
        <LocationSelect value={form.from_location_id} locations={locations}
                        onChange={(v) => setForm({ ...form, from_location_id: v })}/>
      </Field>
      <Field label="Количество *">
        <input type="number" min={1} value={form.quantity}
               onChange={(e) => setForm({ ...form, quantity: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Отчёт об операции" hint="Привяжите расход к отправленному отчёту — это важно для контроля потерь.">
        <select value={form.operation_report_id}
                onChange={(e) => setForm({ ...form, operation_report_id: e.target.value })}
                className="w-full border rounded px-3 py-2 text-sm">
          <option value="">— без отчёта —</option>
          {reports.map((r) => (
            <option key={r.id} value={r.id}>
              #{r.id} · {r.operation_date} · {r.operation_type} · {r.doctor_name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Заметка">
        <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy}
              className="w-full bg-amber-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Списать на операцию'}
      </button>
    </Modal>
  )
}

function ReturnModal({ item, locations, onClose, onDone }) {
  const [form, setForm] = useState({
    from_location_id: item.balances.find((b) => b.quantity > 0)?.location_id || '',
    to_location_id: '', quantity: 1, note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      await returnItem({ item_id: item.id, ...form,
                         from_location_id: Number(form.from_location_id),
                         to_location_id: Number(form.to_location_id),
                         quantity: Number(form.quantity) })
      onDone()
    } catch (e) { setErr(e.response?.data?.detail || 'Ошибка') }
    finally { setBusy(false) }
  }

  return (
    <Modal title={`↶ Возврат · ${item.article}`} onClose={onClose}>
      {err && <div className="bg-red-50 text-red-700 rounded p-2 text-sm mb-2">{err}</div>}
      <Field label="Откуда (из оперблока) *">
        <LocationSelect value={form.from_location_id} locations={locations}
                        exclude={form.to_location_id}
                        onChange={(v) => setForm({ ...form, from_location_id: v })}/>
      </Field>
      <Field label="Куда (обратно на склад) *">
        <LocationSelect value={form.to_location_id} locations={locations}
                        exclude={form.from_location_id}
                        onChange={(v) => setForm({ ...form, to_location_id: v })}/>
      </Field>
      <Field label="Количество *">
        <input type="number" min={1} value={form.quantity}
               onChange={(e) => setForm({ ...form, quantity: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Заметка">
        <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy}
              className="w-full bg-indigo-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Вернуть'}
      </button>
    </Modal>
  )
}

function InventoryModal({ item, locations, onClose, onDone }) {
  const firstBal = item.balances[0]
  const [form, setForm] = useState({
    location_id: firstBal?.location_id || '',
    actual_quantity: firstBal?.quantity ?? 0, note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const currentBalance = item.balances.find((b) => b.location_id === Number(form.location_id))?.quantity ?? 0

  const submit = async () => {
    setBusy(true); setErr('')
    try {
      const resp = await inventory({ item_id: item.id, ...form,
                                     location_id: Number(form.location_id),
                                     actual_quantity: Number(form.actual_quantity) })
      if (resp.movement_id === null) {
        setErr(resp.note || 'Остаток не изменился')
      } else {
        onDone()
      }
    } catch (e) { setErr(e.response?.data?.detail || 'Ошибка') }
    finally { setBusy(false) }
  }

  return (
    <Modal title={`📋 Инвентаризация · ${item.article}`} onClose={onClose}>
      {err && <div className="bg-amber-50 text-amber-800 rounded p-2 text-sm mb-2">{err}</div>}
      <Field label="Локация *">
        <LocationSelect value={form.location_id} locations={locations}
                        onChange={(v) => setForm({ ...form, location_id: v })}/>
      </Field>
      <Field label="Учётный остаток" hint="По данным системы">
        <input disabled value={currentBalance}
               className="w-full border rounded px-3 py-2 text-sm bg-gray-100"/>
      </Field>
      <Field label="Фактический остаток *" hint="Что реально посчитали на локации">
        <input type="number" min={0} value={form.actual_quantity}
               onChange={(e) => setForm({ ...form, actual_quantity: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Заметка">
        <input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy}
              className="w-full bg-purple-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Зафиксировать'}
      </button>
    </Modal>
  )
}

function WriteOffModal({ item, locations, onClose, onDone }) {
  const [form, setForm] = useState({
    from_location_id: item.balances.find((b) => b.quantity > 0)?.location_id || '',
    quantity: 1, note: '',
  })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const submit = async () => {
    if (!window.confirm('Списать без возможности отмены?')) return
    setBusy(true); setErr('')
    try {
      await writeOff({ item_id: item.id, ...form,
                       from_location_id: Number(form.from_location_id),
                       quantity: Number(form.quantity) })
      onDone()
    } catch (e) { setErr(e.response?.data?.detail || 'Ошибка') }
    finally { setBusy(false) }
  }

  return (
    <Modal title={`🗑 Списание · ${item.article}`} onClose={onClose}>
      {err && <div className="bg-red-50 text-red-700 rounded p-2 text-sm mb-2">{err}</div>}
      <Field label="С какой локации *">
        <LocationSelect value={form.from_location_id} locations={locations}
                        onChange={(v) => setForm({ ...form, from_location_id: v })}/>
      </Field>
      <Field label="Количество *">
        <input type="number" min={1} value={form.quantity}
               onChange={(e) => setForm({ ...form, quantity: e.target.value })}
               className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <Field label="Причина *" hint="Пример: истёк срок, повреждена упаковка">
        <textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })}
                  rows={2} className="w-full border rounded px-3 py-2 text-sm"/>
      </Field>
      <button onClick={submit} disabled={busy || !form.note.trim()}
              className="w-full bg-red-600 text-white rounded-lg py-2 font-medium disabled:opacity-50">
        {busy ? '…' : 'Списать'}
      </button>
    </Modal>
  )
}
