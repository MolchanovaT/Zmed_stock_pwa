import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { BrowserMultiFormatReader } from '@zxing/browser'
import { useAuth } from '../store/auth'
import { scanBarcode } from '../api/clinic_stock'

/**
 * Сканирование штрихкодов.
 *
 * Два способа ввода:
 *  (а) Камера телефона/планшета через @zxing/browser (EAN-13, Code-128, QR,
 *      DataMatrix и др.).
 *  (б) USB/BT-сканер — эмулирует клавиатуру. Поле ввода с автофокусом
 *      ловит ввод; сканер обычно завершает Enter'ом.
 *
 * После декодирования делаем GET /scan?barcode=X и показываем найденные партии.
 */
export default function ClinicStockScanPage() {
  const navigate = useNavigate()
  const { user } = useAuth()

  const videoRef = useRef(null)
  const inputRef = useRef(null)
  const readerRef = useRef(null)
  const controlsRef = useRef(null)

  const [cameraOn, setCameraOn] = useState(false)
  const [barcode, setBarcode] = useState('')
  const [results, setResults] = useState(null)       // null = не искали, [] = не нашли
  const [error, setError] = useState('')
  const [searching, setSearching] = useState(false)

  // Автофокус на поле — ловит ввод клавиатурного сканера
  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  const stopCamera = () => {
    try {
      controlsRef.current?.stop?.()
    } catch { /* ignore */ }
    controlsRef.current = null
    setCameraOn(false)
  }

  useEffect(() => () => stopCamera(), [])  // cleanup при размонтировании

  const handleBarcode = async (code) => {
    if (!code) return
    setBarcode(code)
    setSearching(true); setError('')
    try {
      const items = await scanBarcode(code)
      setResults(items)
    } catch (e) {
      setError(e.response?.data?.detail || 'Ошибка поиска')
      setResults([])
    } finally {
      setSearching(false)
    }
  }

  const startCamera = async () => {
    setError('')
    try {
      if (!readerRef.current) {
        readerRef.current = new BrowserMultiFormatReader()
      }
      const devices = await BrowserMultiFormatReader.listVideoInputDevices()
      // Предпочитаем заднюю камеру
      const back = devices.find((d) => /back|rear|environment/i.test(d.label)) || devices[0]
      if (!back) {
        setError('Камера не найдена')
        return
      }
      controlsRef.current = await readerRef.current.decodeFromVideoDevice(
        back.deviceId, videoRef.current,
        (result, err) => {
          if (result) {
            const code = result.getText()
            stopCamera()
            handleBarcode(code)
          }
        }
      )
      setCameraOn(true)
    } catch (e) {
      setError('Не удалось включить камеру: ' + (e.message || e))
    }
  }

  const onKbSubmit = (e) => {
    e.preventDefault()
    handleBarcode(barcode.trim())
  }

  const clear = () => {
    setBarcode(''); setResults(null); setError('')
    inputRef.current?.focus()
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/clinic-stock')}
                  className="text-gray-500 hover:text-brand-600 text-sm">← Назад</button>
          <span className="text-xl ml-3">📷</span>
          <span className="font-bold text-gray-800">Сканер штрихкодов</span>
        </div>
        <span className="text-sm text-gray-500">{user?.username}</span>
      </header>

      <main className="max-w-xl mx-auto px-4 py-6 space-y-5">
        {error && (
          <div className="bg-red-50 text-red-700 rounded p-3 text-sm">{error}</div>
        )}

        {/* Поле для клавиатурного сканера */}
        <form onSubmit={onKbSubmit} className="bg-white rounded-xl border p-4 space-y-2">
          <label className="block text-xs text-gray-500">Введите или отсканируйте код</label>
          <div className="flex gap-2">
            <input ref={inputRef} value={barcode}
                   onChange={(e) => setBarcode(e.target.value)}
                   autoFocus
                   placeholder="EAN-13 / DataMatrix / артикул"
                   className="flex-1 border rounded px-3 py-2 text-sm font-mono"/>
            <button type="submit" disabled={!barcode.trim() || searching}
                    className="bg-brand-600 text-white rounded px-4 py-2 text-sm font-medium disabled:opacity-50">
              {searching ? '…' : 'Найти'}
            </button>
            {barcode && (
              <button type="button" onClick={clear}
                      className="text-gray-400 hover:text-gray-600 text-sm px-2">✕</button>
            )}
          </div>
          <p className="text-xs text-gray-400">
            USB/BT-сканер завершит ввод сам (Enter). Для камеры нажмите ниже.
          </p>
        </form>

        {/* Камера */}
        <div className="bg-white rounded-xl border p-4">
          {!cameraOn ? (
            <button onClick={startCamera}
                    className="w-full bg-sky-600 hover:bg-sky-700 text-white rounded-lg py-3 font-medium">
              📷 Включить камеру
            </button>
          ) : (
            <>
              <video ref={videoRef} className="w-full rounded border"
                     style={{ aspectRatio: '4/3', objectFit: 'cover' }}/>
              <button onClick={stopCamera}
                      className="mt-2 w-full bg-gray-700 text-white rounded-lg py-2 text-sm">
                Остановить камеру
              </button>
            </>
          )}
        </div>

        {/* Результаты */}
        {results !== null && (
          <div className="bg-white rounded-xl border p-4">
            <h3 className="font-semibold text-gray-800 mb-2">
              {results.length === 0
                ? `Партия со штрихкодом/артикулом «${barcode}» не найдена`
                : `Найдено: ${results.length}`}
            </h3>
            {results.length === 0 ? (
              <p className="text-sm text-gray-500">
                Проверьте код или заведите приход с таким штрихкодом из главной страницы ОХ.
              </p>
            ) : (
              <ul className="divide-y">
                {results.map((it) => (
                  <li key={it.id} className="py-3">
                    <div className="font-medium text-gray-800">
                      {it.article} · {it.nomenclature}
                    </div>
                    <div className="text-xs text-gray-500 mb-1">
                      {it.characteristic && <>{it.characteristic} · </>}
                      Lot: {it.lot_number || '—'} · Срок: {it.expiration_date || '—'}
                    </div>
                    <div className="text-sm">
                      {it.balances.length === 0 ? (
                        <span className="text-gray-400">нет на остатке</span>
                      ) : (
                        it.balances.map((b) => (
                          <span key={b.location_id} className="inline-block mr-3">
                            <span className="text-gray-500">{b.location_name}:</span>{' '}
                            <span className="font-semibold">{b.quantity}</span>
                          </span>
                        ))
                      )}
                    </div>
                    <button onClick={() => navigate(`/clinic-stock?item=${it.id}`)}
                            className="text-brand-600 hover:underline text-xs mt-1">
                      Открыть в учёте →
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
