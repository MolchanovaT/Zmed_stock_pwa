import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../store/auth'
import {
  createReport, getReport, patchReport, deleteReport,
  uploadReportFile, openReportFile, deleteReportFile,
  suggestDoctors, suggestOperationTypes, openReportPdf,
  getReportAudit, listTags, setReportTags,
} from '../api/clinic_reports'
import { requestOtp } from '../api/otp'

const AUDIT_LABEL = {
  submit: { text: 'Отправлен', cls: 'bg-emerald-100 text-emerald-800' },
  edit_after_submit: { text: 'Правка после отправки', cls: 'bg-amber-100 text-amber-800' },
  delete_submitted: { text: 'Удалён', cls: 'bg-red-100 text-red-800' },
}

const emptyImplant = () => ({ article: '', nomenclature: '', qty: 1, lot_number: '', serial: '' })

// Эвристика «похоже на ФИО»: ≥2 слов из 2+ букв с заглавной
const looksLikePersonalName = (s) => {
  if (!s) return false
  const words = s.trim().split(/\s+/).filter((w) => /^[А-ЯЁA-Z][а-яёa-z-]{1,}$/.test(w))
  return words.length >= 2
}

export default function ClinicReportFormPage() {
  const { id } = useParams()
  const isNew = id === 'new' || !id
  const navigate = useNavigate()
  const { user } = useAuth()

  const [form, setForm] = useState({
    patient_code: '',
    operation_date: new Date().toISOString().slice(0, 10),
    department: '',
    doctor_name: '',
    operation_type: '',
    diagnosis_text: '',
    complications: '',
    notes: '',
    implants_used: [emptyImplant()],
    status: 'draft',
  })
  const [files, setFiles] = useState([])
  const [reportId, setReportId] = useState(null)
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [doctorSuggests, setDoctorSuggests] = useState([])
  const [opTypeSuggests, setOpTypeSuggests] = useState([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)
  const [step, setStep] = useState(0)   // 0..4; используется только при canEdit
  const [audit, setAudit] = useState([])
  const [availableTags, setAvailableTags] = useState([])
  const [reportTagIds, setReportTagIds] = useState([])
  // OTP-режим: если сервер отдал 400/401 с подсказкой — показываем модалку
  const [otp, setOtp] = useState(null)   // {purpose, sentTo, code, pending}

  const canEdit = isNew || (form.status === 'draft')

  // Шаги и их валидация. Опциональные — валидация пустая.
  const STEPS = [
    { label: 'Операция', hint: 'Код операции, дата, отделение' },
    { label: 'Врач и тип', hint: 'ФИО врача и тип операции' },
    { label: 'Диагноз',  hint: 'Код МКБ-10 или краткая формулировка' },
    { label: 'Импланты', hint: 'Что использовали в операции' },
    { label: 'Файлы и заметки', hint: 'Фото/скан протокола, осложнения' },
  ]

  const validateStep = (idx) => {
    if (idx === 0) {
      if (!form.patient_code.trim()) return 'Укажите код операции'
      if (!form.operation_date) return 'Укажите дату операции'
    }
    if (idx === 1) {
      if (!form.doctor_name.trim()) return 'Укажите ФИО врача'
      if (!form.operation_type.trim()) return 'Укажите тип операции'
    }
    return null
  }

  // Загрузка существующего отчёта
  useEffect(() => {
    if (isNew) return
    getReport(id)
      .then((r) => {
        setForm({
          patient_code: r.patient_code,
          operation_date: r.operation_date,
          department: r.department || '',
          doctor_name: r.doctor_name,
          operation_type: r.operation_type,
          diagnosis_text: r.diagnosis_text || '',
          complications: r.complications || '',
          notes: r.notes || '',
          implants_used: r.implants_used?.length ? r.implants_used : [emptyImplant()],
          status: r.status,
        })
        setFiles(r.files || [])
        setReportId(r.id)
        setReportTagIds((r.tags || []).map((t) => t.id))
      })
      .catch((e) => setError(e.response?.data?.detail || 'Отчёт не найден'))
      .finally(() => setLoading(false))
  }, [id, isNew])

  useEffect(() => {
    suggestDoctors('').then(setDoctorSuggests).catch(() => {})
    suggestOperationTypes('').then(setOpTypeSuggests).catch(() => {})
    listTags().then(setAvailableTags).catch(() => {})
  }, [])

  const toggleTag = async (tagId) => {
    if (!reportId) return  // Пока нет id — сохранять некуда (сначала сохрани черновик)
    const next = reportTagIds.includes(tagId)
      ? reportTagIds.filter((x) => x !== tagId)
      : [...reportTagIds, tagId]
    setReportTagIds(next)
    try {
      await setReportTags(reportId, next)
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка тегов')
      // Откатываем визуал
      setReportTagIds((prev) => reportTagIds)
    }
  }

  // Audit log: подтягиваем, только если отчёт существует и уже отправлен.
  useEffect(() => {
    if (isNew || !reportId || form.status === 'draft') { setAudit([]); return }
    getReportAudit(reportId).then(setAudit).catch(() => setAudit([]))
  }, [isNew, reportId, form.status])

  const upd = (field, value) => setForm((f) => ({ ...f, [field]: value }))

  const updImplant = (idx, field, value) => {
    setForm((f) => {
      const copy = f.implants_used.slice()
      copy[idx] = { ...copy[idx], [field]: value }
      return { ...f, implants_used: copy }
    })
  }
  const addImplantRow = () =>
    setForm((f) => ({ ...f, implants_used: [...f.implants_used, emptyImplant()] }))
  const removeImplantRow = (idx) =>
    setForm((f) => ({
      ...f,
      implants_used: f.implants_used.length <= 1 ? f.implants_used
        : f.implants_used.filter((_, i) => i !== idx),
    }))

  const validate = (requireAllForSubmit = false) => {
    if (!form.patient_code.trim()) return 'Укажите код операции'
    if (!form.operation_date) return 'Укажите дату операции'
    if (!form.doctor_name.trim()) return 'Укажите ФИО врача'
    if (!form.operation_type.trim()) return 'Укажите тип операции'
    if (requireAllForSubmit) {
      // На submit — все обязательные уже проверены выше.
      // Доп. правило: если implants_used заполнен — требуем nomenclature.
      for (const imp of form.implants_used) {
        if (imp.article || imp.nomenclature || imp.lot_number || imp.serial || imp.qty > 1) {
          if (!imp.nomenclature.trim() && !imp.article.trim()) {
            return 'В строке импланта укажите артикул или номенклатуру'
          }
        }
      }
    }
    return null
  }

  const buildBody = () => {
    const implants = form.implants_used
      .filter((i) => i.article || i.nomenclature || i.lot_number || i.serial)
      .map((i) => ({
        article: i.article.trim(),
        nomenclature: i.nomenclature.trim(),
        qty: Number(i.qty) || 1,
        lot_number: (i.lot_number || '').trim(),
        serial: (i.serial || '').trim(),
      }))
    return {
      patient_code: form.patient_code.trim(),
      operation_date: form.operation_date,
      department: form.department.trim() || null,
      doctor_name: form.doctor_name.trim(),
      operation_type: form.operation_type.trim(),
      diagnosis_text: form.diagnosis_text.trim() || null,
      complications: form.complications.trim() || null,
      notes: form.notes.trim() || null,
      implants_used: implants,
    }
  }

  const saveDraft = async () => {
    const err = validate(false)
    if (err) { setError(err); return }
    setSaving(true); setError('')
    try {
      const body = { ...buildBody(), status: 'draft' }
      if (isNew && !reportId) {
        const created = await createReport(body)
        setReportId(created.id)
        navigate(`/clinic-reports/${created.id}`, { replace: true })
      } else {
        await patchReport(reportId, body)
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка сохранения')
    } finally {
      setSaving(false)
    }
  }

  const _doSubmit = async (otpCode = null) => {
    setSaving(true); setError('')
    try {
      const body = { ...buildBody(), status: 'submitted' }
      if (otpCode) body.otp_code = otpCode
      if (isNew && !reportId) {
        const created = await createReport(body)
        navigate(`/clinic-reports/${created.id}`, { replace: true })
      } else {
        await patchReport(reportId, body)
        setForm((f) => ({ ...f, status: 'submitted' }))
      }
      setOtp(null)
      return true
    } catch (e) {
      const detail = e.response?.data?.detail || 'Ошибка отправки'
      const status = e.response?.status
      // Если сервер требует OTP (400/401 с характерной подсказкой) — показываем модалку
      if ((status === 400 || status === 401)
          && /OTP|код/i.test(String(detail))) {
        const purpose = (isNew && !reportId)
          ? `report_submit_new:unknown` // target_org_id сервер подставит сам
          : `report_submit:${reportId}`
        setOtp({ purpose, sentTo: null, code: '', pending: false, error: detail })
      } else {
        setError(detail)
      }
      return false
    } finally {
      setSaving(false)
    }
  }

  const submit = async () => {
    const err = validate(true)
    if (err) { setError(err); return }
    if (!window.confirm('После отправки отчёт нельзя будет редактировать. Отправить?')) return
    await _doSubmit()
  }

  const requestOtpCode = async () => {
    if (!otp) return
    setOtp({ ...otp, pending: true, error: '' })
    try {
      const r = await requestOtp(otp.purpose)
      setOtp((prev) => ({ ...prev, sentTo: r.sent_to, pending: false, error: '' }))
    } catch (e) {
      setOtp((prev) => ({
        ...prev, pending: false,
        error: e.response?.data?.detail || 'Не удалось отправить код',
      }))
    }
  }

  const submitWithOtp = async () => {
    if (!otp?.code?.trim()) {
      setOtp({ ...otp, error: 'Введите код из email' })
      return
    }
    await _doSubmit(otp.code.trim())
  }

  const removeDraft = async () => {
    if (!reportId) { navigate('/clinic-reports'); return }
    if (!window.confirm('Удалить этот черновик?')) return
    try {
      await deleteReport(reportId)
      navigate('/clinic-reports')
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка удаления')
    }
  }

  const onPickFiles = async (e) => {
    if (!reportId) {
      setError('Сначала сохраните черновик, потом прикрепляйте файлы')
      e.target.value = ''
      return
    }
    const picked = Array.from(e.target.files || [])
    e.target.value = ''
    if (!picked.length) return
    setUploading(true); setError('')
    try {
      for (const f of picked) {
        const added = await uploadReportFile(reportId, f)
        setFiles((prev) => [...prev, added])
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Ошибка загрузки файла')
    } finally {
      setUploading(false)
    }
  }

  const removeFile = async (fileId) => {
    if (!window.confirm('Удалить этот файл?')) return
    try {
      await deleteReportFile(reportId, fileId)
      setFiles((prev) => prev.filter((f) => f.id !== fileId))
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка удаления')
    }
  }

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-gray-400">Загрузка…</div>
  }

  const showPersonalWarning = looksLikePersonalName(form.patient_code)

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/clinic-reports')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← Список</button>
          <span className="text-xl ml-3">📋</span>
          <span className="font-bold text-gray-800">
            {isNew ? 'Новый отчёт' : `Отчёт #${reportId}`}
          </span>
          {!isNew && (
            <span className={`ml-3 text-xs px-2 py-0.5 rounded-full font-medium
              ${form.status === 'draft' ? 'bg-amber-100 text-amber-800' : 'bg-emerald-100 text-emerald-800'}`}>
              {form.status === 'draft' ? 'Черновик' : 'Отправлен'}
            </span>
          )}
        </div>
        <span className="text-sm text-gray-500">{user?.username}</span>
      </header>

      <main className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {error && (
          <div className="bg-red-50 text-red-700 rounded p-3 text-sm">{error}</div>
        )}

        {/* Прогресс-бар. Только в режиме редактирования. */}
        {canEdit && (
          <div className="bg-white rounded-xl border p-4">
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className="font-semibold text-gray-800">
                Шаг {step + 1} из {STEPS.length}: {STEPS[step].label}
              </div>
              <div className="flex gap-1">
                {STEPS.map((_, i) => (
                  <button key={i}
                          onClick={() => {
                            // Назад — свободно; вперёд — только если предыдущие валидны
                            if (i <= step) { setStep(i); setError(''); return }
                            for (let k = step; k < i; k++) {
                              const err = validateStep(k)
                              if (err) { setError(err); return }
                            }
                            setStep(i); setError('')
                          }}
                          className={`w-7 h-2 rounded-full transition
                            ${i === step ? 'bg-brand-600'
                              : i < step ? 'bg-brand-300' : 'bg-gray-200'}`}
                          aria-label={`Перейти к шагу ${i + 1}`}/>
                ))}
              </div>
            </div>
            <div className="text-xs text-gray-500">{STEPS[step].hint}</div>
          </div>
        )}

        {/* Шаг 1: Операция (patient_code, date, department) */}
        {(!canEdit || step === 0) && (
        <section className="bg-white rounded-xl border p-5 space-y-4">
          <h2 className="font-semibold text-gray-800">1. Об операции</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Код операции *</label>
              <input value={form.patient_code} disabled={!canEdit}
                     maxLength={32}
                     onChange={(e) => upd('patient_code', e.target.value)}
                     placeholder="OP-2026-00123"
                     className="w-full border rounded px-3 py-2 text-sm"/>
              {showPersonalWarning && (
                <p className="text-xs text-amber-700 mt-1">
                  ⚠️ Похоже на ФИО. Не вводите ПДн пациента — только обезличенный код.
                </p>
              )}
              <p className="text-xs text-gray-400 mt-1">
                Любой обезличенный идентификатор. НЕ ФИО, НЕ дата рождения, НЕ адрес.
              </p>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Дата операции *</label>
              <input type="date" value={form.operation_date} disabled={!canEdit}
                     onChange={(e) => upd('operation_date', e.target.value)}
                     className="w-full border rounded px-3 py-2 text-sm"/>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs text-gray-500 mb-1">Отделение</label>
              <input value={form.department} disabled={!canEdit}
                     maxLength={100}
                     onChange={(e) => upd('department', e.target.value)}
                     placeholder="нейрохирургия"
                     className="w-full border rounded px-3 py-2 text-sm"/>
            </div>
          </div>
        </section>
        )}

        {/* Шаг 2: Врач и тип операции */}
        {(!canEdit || step === 1) && (
        <section className="bg-white rounded-xl border p-5 space-y-4">
          <h2 className="font-semibold text-gray-800">2. Врач и тип операции</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">ФИО врача *</label>
              <input value={form.doctor_name} disabled={!canEdit}
                     maxLength={100} list="doctor-suggests"
                     onChange={(e) => upd('doctor_name', e.target.value)}
                     className="w-full border rounded px-3 py-2 text-sm"/>
              <datalist id="doctor-suggests">
                {doctorSuggests.map((d) => <option key={d} value={d}/>)}
              </datalist>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Тип операции *</label>
              <input value={form.operation_type} disabled={!canEdit}
                     maxLength={200} list="op-type-suggests"
                     onChange={(e) => upd('operation_type', e.target.value)}
                     placeholder="напр.: Транспедикулярная фиксация"
                     className="w-full border rounded px-3 py-2 text-sm"/>
              <datalist id="op-type-suggests">
                {opTypeSuggests.map((t) => <option key={t} value={t}/>)}
              </datalist>
            </div>
          </div>
        </section>
        )}

        {/* Шаг 3: диагноз */}
        {(!canEdit || step === 2) && (
        <section className="bg-white rounded-xl border p-5 space-y-3">
          <h2 className="font-semibold text-gray-800">3. Диагноз</h2>
          <textarea value={form.diagnosis_text} disabled={!canEdit}
                    maxLength={500} rows={3}
                    onChange={(e) => upd('diagnosis_text', e.target.value)}
                    placeholder="Напр.: M51.1 Поражения межпозвоночных дисков поясничного отдела с радикулопатией"
                    className="w-full border rounded px-3 py-2 text-sm"/>
          <p className="text-xs text-gray-400">
            Код МКБ-10 или краткая формулировка. Без ПДн пациента и анамнеза. До 500 символов.
          </p>
        </section>
        )}

        {/* Шаг 4: импланты */}
        {(!canEdit || step === 3) && (
        <section className="bg-white rounded-xl border p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">4. Использованные импланты</h2>
            {canEdit && (
              <button onClick={addImplantRow}
                      className="text-brand-600 hover:text-brand-700 text-sm font-medium">
                + Добавить
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b">
                  <th className="py-1 pr-2">Артикул</th>
                  <th className="py-1 pr-2">Номенклатура</th>
                  <th className="py-1 pr-2">Кол-во</th>
                  <th className="py-1 pr-2">Lot</th>
                  <th className="py-1 pr-2">Серийник</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {form.implants_used.map((imp, i) => (
                  <tr key={i} className="border-b last:border-b-0">
                    <td className="py-1 pr-2">
                      <input value={imp.article} disabled={!canEdit}
                             onChange={(e) => updImplant(i, 'article', e.target.value)}
                             className="w-24 border rounded px-2 py-1 text-sm"/>
                    </td>
                    <td className="py-1 pr-2">
                      <input value={imp.nomenclature} disabled={!canEdit}
                             onChange={(e) => updImplant(i, 'nomenclature', e.target.value)}
                             className="w-full border rounded px-2 py-1 text-sm"/>
                    </td>
                    <td className="py-1 pr-2">
                      <input type="number" min={1} value={imp.qty} disabled={!canEdit}
                             onChange={(e) => updImplant(i, 'qty', e.target.value)}
                             className="w-16 border rounded px-2 py-1 text-sm"/>
                    </td>
                    <td className="py-1 pr-2">
                      <input value={imp.lot_number} disabled={!canEdit}
                             onChange={(e) => updImplant(i, 'lot_number', e.target.value)}
                             className="w-24 border rounded px-2 py-1 text-sm"/>
                    </td>
                    <td className="py-1 pr-2">
                      <input value={imp.serial} disabled={!canEdit}
                             onChange={(e) => updImplant(i, 'serial', e.target.value)}
                             className="w-28 border rounded px-2 py-1 text-sm"/>
                    </td>
                    <td className="py-1">
                      {canEdit && form.implants_used.length > 1 && (
                        <button onClick={() => removeImplantRow(i)}
                                className="text-gray-400 hover:text-red-500 text-sm">✕</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        )}

        {/* Шаг 5: теги + осложнения и заметки + файлы */}
        {(!canEdit || step === 4) && availableTags.length > 0 && (
        <section className="bg-white rounded-xl border p-5 space-y-3">
          <h2 className="font-semibold text-gray-800">5a. Теги</h2>
          {!reportId && (
            <p className="text-xs text-amber-700">
              Чтобы назначить теги — сначала сохраните черновик.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {availableTags.map((t) => {
              const active = reportTagIds.includes(t.id)
              return (
                <button key={t.id}
                        onClick={() => toggleTag(t.id)}
                        disabled={!canEdit || !reportId}
                        type="button"
                        style={active
                          ? { background: t.color, color: '#fff', borderColor: t.color }
                          : { color: t.color, borderColor: t.color }}
                        className="px-3 py-1 text-xs font-medium rounded-full border transition disabled:opacity-50">
                  {active && '✓ '}{t.name}
                </button>
              )
            })}
          </div>
        </section>
        )}

        {(!canEdit || step === 4) && (
        <section className="bg-white rounded-xl border p-5 space-y-4">
          <h2 className="font-semibold text-gray-800">5. Осложнения и заметки</h2>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Осложнения</label>
            <textarea value={form.complications} disabled={!canEdit}
                      maxLength={2000} rows={2}
                      onChange={(e) => upd('complications', e.target.value)}
                      className="w-full border rounded px-3 py-2 text-sm"/>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Заметки</label>
            <textarea value={form.notes} disabled={!canEdit}
                      maxLength={2000} rows={2}
                      onChange={(e) => upd('notes', e.target.value)}
                      className="w-full border rounded px-3 py-2 text-sm"/>
          </div>
        </section>
        )}

        {/* Шаг 5 (вторая часть): файлы */}
        {(!canEdit || step === 4) && (
        <section className="bg-white rounded-xl border p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-gray-800">6. Фото и сканы</h2>
            {canEdit && (
              <>
                <input ref={fileInputRef} type="file" multiple hidden
                       accept="image/jpeg,image/png,image/webp,image/heic,image/heif,application/pdf"
                       onChange={onPickFiles}/>
                <button onClick={() => fileInputRef.current?.click()}
                        disabled={uploading}
                        className="text-brand-600 hover:text-brand-700 text-sm font-medium disabled:text-gray-400">
                  {uploading ? 'Загрузка…' : '+ Прикрепить'}
                </button>
              </>
            )}
          </div>
          <p className="text-xs text-gray-400">
            До 10 файлов, каждый до 20 МБ. JPG, PNG, WEBP, HEIC, PDF.
            {isNew && !reportId && <> Сначала сохраните как черновик — после этого можно прикрепить файлы.</>}
          </p>
          {files.length === 0 ? (
            <p className="text-sm text-gray-400">Файлов пока нет</p>
          ) : (
            <ul className="space-y-2">
              {files.map((f) => (
                <li key={f.id}
                    className="flex items-center justify-between gap-3 bg-gray-50 rounded p-2 text-sm">
                  <button
                    onClick={() => openReportFile(reportId, f.id, f.original_name)}
                    className="text-left truncate flex-1 hover:text-brand-700">
                    📎 {f.original_name || `file_${f.id}`}
                    <span className="text-xs text-gray-400 ml-2">
                      {f.size_bytes ? `${Math.round(f.size_bytes / 1024)} КБ` : ''}
                    </span>
                  </button>
                  {canEdit && (
                    <button onClick={() => removeFile(f.id)}
                            className="text-gray-400 hover:text-red-500">✕</button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
        )}

        {/* Нижняя панель навигации wizard'а */}
        {canEdit && (
          <div className="flex gap-3 flex-wrap">
            {step > 0 && (
              <button onClick={() => { setStep(step - 1); setError('') }}
                      className="bg-white border rounded-lg px-5 py-2 text-gray-700 hover:bg-gray-50">
                ← Назад
              </button>
            )}
            <button onClick={saveDraft} disabled={saving}
                    className="bg-white border border-brand-500 text-brand-600 hover:bg-brand-50 rounded-lg px-5 py-2 font-medium disabled:opacity-50">
              💾 Черновик
            </button>
            {step < STEPS.length - 1 && (
              <button
                onClick={() => {
                  const err = validateStep(step)
                  if (err) { setError(err); return }
                  setStep(step + 1); setError('')
                }}
                className="ml-auto bg-brand-600 hover:bg-brand-700 text-white rounded-lg px-5 py-2 font-medium"
              >
                Далее →
              </button>
            )}
            {step === STEPS.length - 1 && (
              <button onClick={submit} disabled={saving}
                      className="ml-auto bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-5 py-2 font-medium disabled:opacity-50">
                ✅ Отправить
              </button>
            )}
            {!isNew && (
              <button onClick={removeDraft} disabled={saving}
                      className="text-red-500 hover:text-red-600 text-sm self-center">
                🗑 Удалить
              </button>
            )}
          </div>
        )}

        {!canEdit && (
          <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg p-4 text-sm flex items-center justify-between gap-3 flex-wrap">
            <span>Этот отчёт отправлен и больше не редактируется.</span>
            <button onClick={() => openReportPdf(reportId)}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg px-4 py-2 text-sm font-medium">
              📄 Скачать PDF
            </button>
          </div>
        )}

        {!isNew && canEdit && (
          <div className="text-xs text-gray-400">
            Отчёт черновик — PDF будет доступен после отправки.
          </div>
        )}

        {/* OTP-модалка */}
        {otp && (
          <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4">
            <div className="bg-white rounded-xl p-5 w-full max-w-md space-y-3">
              <h3 className="font-semibold text-gray-800">
                Подтверждение подписи
              </h3>
              <p className="text-sm text-gray-600">
                Отправка отчёта требует подтверждения кодом из email.
                Нажмите «Отправить код», затем введите 6 цифр из письма.
              </p>
              {otp.error && (
                <div className="bg-red-50 text-red-700 rounded p-2 text-sm">
                  {otp.error}
                </div>
              )}
              <button
                onClick={requestOtpCode}
                disabled={otp.pending}
                className="w-full bg-brand-600 hover:bg-brand-700 text-white rounded px-4 py-2 text-sm font-medium disabled:opacity-50"
              >
                {otp.sentTo ? 'Отправить код ещё раз' : (otp.pending ? '…' : 'Отправить код')}
              </button>
              {otp.sentTo && (
                <p className="text-xs text-gray-500">Отправлено на {otp.sentTo}</p>
              )}
              <input
                value={otp.code}
                onChange={(e) => setOtp({ ...otp, code: e.target.value.replace(/\D/g, '').slice(0, 6) })}
                placeholder="123456"
                inputMode="numeric" autoComplete="one-time-code"
                className="w-full border rounded px-3 py-2 text-center text-xl tracking-widest font-mono"
              />
              <div className="flex gap-2">
                <button onClick={() => setOtp(null)}
                        className="flex-1 border rounded px-4 py-2 text-sm">
                  Отмена
                </button>
                <button onClick={submitWithOtp} disabled={saving || !otp.code}
                        className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded px-4 py-2 text-sm font-medium disabled:opacity-50">
                  {saving ? '…' : 'Подписать и отправить'}
                </button>
              </div>
            </div>
          </div>
        )}

        {audit.length > 0 && (
          <section className="bg-white rounded-xl border p-5">
            <h2 className="font-semibold text-gray-800 mb-3">История подписания</h2>
            <ul className="space-y-2">
              {audit.map((e) => {
                const meta = AUDIT_LABEL[e.action] || { text: e.action, cls: 'bg-gray-100 text-gray-700' }
                return (
                  <li key={e.id} className="flex items-start gap-3 text-sm">
                    <span className={`${meta.cls} text-xs px-2 py-0.5 rounded-full font-medium whitespace-nowrap`}>
                      {meta.text}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-gray-700">
                        {e.user_name || `user#${e.user_id}`}
                        <span className="text-xs text-gray-400 ml-2">
                          {e.created_at ? new Date(e.created_at).toLocaleString() : ''}
                        </span>
                      </div>
                      {e.note && (
                        <div className="text-xs text-gray-500 mt-0.5">{e.note}</div>
                      )}
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        )}
      </main>
    </div>
  )
}
