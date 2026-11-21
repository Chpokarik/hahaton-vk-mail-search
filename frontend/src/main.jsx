import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Archive, Bookmark, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Inbox,
  LoaderCircle, Mail, MailOpen, Search, X,
} from 'lucide-react'
import '@fontsource-variable/inter'
import '@fontsource-variable/manrope'
import { api } from './api'
import { colorIndex, initials, mailContent, mailDate, number, preview } from './mail'
import { loadSaved, saveLetters, savedSummary } from './saved'
import './style.css'

const PAGE_SIZE = 20
const SEARCH_LIMIT = 50
const SUGGESTIONS = ['Заказы от 20 ноября 2026', 'Счёт на оплату', 'Покупатель хочет вернуть товар']
const IDLE = { status: 'idle' }
const LOADING = { status: 'loading' }

function useRequest(load) {
  const [state, setState] = useState(null)
  const [attempt, retry] = useState(0)

  useEffect(() => {
    if (!load) return
    const controller = new AbortController()
    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ load, attempt, status: 'ready', data })
      },
      () => {
        if (!controller.signal.aborted) setState({ load, attempt, status: 'error' })
      },
    )
    return () => controller.abort()
  }, [load, attempt])

  const current = !load ? IDLE : state?.load === load && state.attempt === attempt ? state : LOADING
  return { ...current, retry: () => retry((previous) => previous + 1) }
}

function Notice({ icon: Icon = Inbox, title, children, action, actionText }) {
  return (
    <div className="notice" role="status">
      <span className="notice-icon"><Icon size={24} strokeWidth={1.7} /></span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action && <button className="text-button" onClick={action}>{actionText}</button>}
    </div>
  )
}

function Sidebar({ boxes, active, health, onChange }) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? boxes : boxes.slice(0, 5)
  const visible = shown.some((box) => box.synthetic_user === active)
    ? shown
    : [...shown, ...boxes.filter((box) => box.synthetic_user === active)]

  const connection = { ready: 'Поиск готов', error: 'Почта недоступна', loading: 'Подключаем почту' }[health.status]

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark"><Mail size={22} strokeWidth={2.1} /></div>
        <span>Почта</span>
      </div>
      <nav className="accounts" aria-label="Почтовые ящики">
        <div className="side-heading"><span>Ящики</span><span>{boxes.length || ''}</span></div>
        <div className="account-list">
          {visible.map(({ synthetic_user, count }) => (
            <button
              key={synthetic_user}
              className="account"
              aria-current={active === synthetic_user ? 'true' : undefined}
              onClick={() => onChange(synthetic_user)}
              title={synthetic_user}
            >
              <span className={`account-icon tint-${colorIndex(synthetic_user)}`}><Archive size={15} strokeWidth={1.85} /></span>
              <span className="account-label">{synthetic_user}</span>
              <span className="account-count">{number.format(count)}</span>
            </button>
          ))}
        </div>
        {boxes.length > 5 && (
          <button className="expand" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
            <ChevronDown size={16} /> {expanded ? 'Свернуть список' : 'Все ящики'}
          </button>
        )}
      </nav>
      {boxes.length > 0 && (
        <label className="mobile-account">
          <span className="sr-only">Почтовый ящик</span>
          <select value={active} onChange={(event) => onChange(event.target.value)}>
            {boxes.map(({ synthetic_user }) => <option key={synthetic_user}>{synthetic_user}</option>)}
          </select>
          <ChevronDown size={16} />
        </label>
      )}
      <div className="connection" role="status">
        <span className={`connection-dot ${health.status}`} />
        <div>
          <span>{connection}</span>
          {health.status === 'ready' && (
            <small>{number.format(health.data.documents)} писем</small>
          )}
          {health.status === 'error' && <button className="text-button" onClick={health.retry}>Перепроверить</button>}
        </div>
      </div>
    </aside>
  )
}

function SearchPanel({ draft, setDraft, onSearch }) {
  const inputRef = useRef(null)

  useEffect(() => {
    function focusSearch(event) {
      if (event.key.toLowerCase() === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        inputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [])

  return (
    <section className="search-panel" aria-labelledby="search-heading">
      <div className="search-content">
        <h1 id="search-heading">Поиск по почте</h1>
        <form className="search-form" role="search" onSubmit={(event) => { event.preventDefault(); onSearch(draft) }}>
          <Search size={21} className="search-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            aria-label="Поиск по письмам"
            placeholder="Например, какие заказы пришли вчера?"
            maxLength={1000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K'}</kbd>
          <button type="submit" disabled={!draft.trim()}>Найти</button>
        </form>
        <div className="suggestions">
          {SUGGESTIONS.map((suggestion) => (
            <button key={suggestion} onClick={() => onSearch(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

function Avatar({ content, id, large = false }) {
  const tint = colorIndex(content.hasSender ? content.sender : id)
  return (
    <span className={`avatar tint-${tint}${large ? ' avatar-large' : ''}`} aria-hidden="true">
      {content.hasSender ? initials(content.sender) : <Mail size={large ? 21 : 17} strokeWidth={1.8} />}
    </span>
  )
}

function MailRow({ item, selected, onOpen }) {
  const content = mailContent(item)
  return (
    <li>
      <button className="mail-row" aria-current={selected ? 'true' : undefined} onClick={onOpen}>
        <Avatar content={content} id={item.doc_id} />
        <span className="row-content">
          <span className="row-meta">
            <span className="sender">{content.sender}</span>
            <span className="row-date">{mailDate(item.date)}</span>
          </span>
          <strong className="row-subject">{content.subject}</strong>
          <span className="row-snippet">{preview(content.text) || 'Письмо без текста'}</span>
        </span>
      </button>
    </li>
  )
}

function Reader({ selected, detail, onClose, panelRef, saved, onSave }) {
  if (!selected) {
    return (
      <section className="panel reader reader-empty" aria-label="Просмотр письма">
        <Notice icon={MailOpen} title="Выберите письмо для просмотра" />
      </section>
    )
  }

  const mail = typeof selected.text === 'string' ? selected : detail.data
  const content = mailContent(mail || selected)
  return (
    <section className="panel reader reader-active" aria-label="Просмотр письма" ref={panelRef} tabIndex={-1}>
      <div className="reader-toolbar">
        <span><Mail size={17} /> Письмо</span>
        <div className="reader-actions">
          <button className="icon-button save-button" onClick={() => onSave(mail || selected)} aria-pressed={saved} aria-label={saved ? 'Убрать из избранного' : 'Сохранить в избранное'} title={saved ? 'Убрать из избранного' : 'Сохранить в избранное'}>
            <Bookmark size={19} fill={saved ? 'currentColor' : 'none'} />
          </button>
          <button className="icon-button" onClick={onClose} aria-label="Закрыть письмо"><X size={19} /></button>
        </div>
      </div>
      <article className="letter" key={selected.doc_id}>
        <h2>{content.subject}</h2>
        <div className="letter-meta">
          <Avatar content={content} id={selected.doc_id} large />
          <div><strong>{content.sender}</strong><span>{mailDate((mail || selected).date, true)}</span></div>
        </div>
        {mail && <div className="letter-text">{content.text || 'Письмо без текста.'}</div>}
        {!mail && detail.status === 'loading' && <Notice icon={LoaderCircle} title="Загружаем письмо" />}
        {!mail && detail.status === 'error' && (
          <Notice icon={MailOpen} title="Письмо не загрузилось" action={detail.retry} actionText="Повторить">
            {content.text || 'Попробуйте загрузить письмо снова.'}
          </Notice>
        )}
      </article>
    </section>
  )
}

function Workspace({ mailbox }) {
  const id = mailbox.synthetic_user
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [date, setDate] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(null)
  const [showSaved, setShowSaved] = useState(false)
  const [saved, setSaved] = useState(() => loadSaved(id))
  const [storageFailed, setStorageFailed] = useState(false)
  const panelRef = useRef(null)
  const listRef = useRef(null)
  const openButton = useRef(null)

  const searchDate = query ? date : ''
  const loadRows = useCallback((signal) => query
    ? api.search(id, query, searchDate, SEARCH_LIMIT, signal)
    : api.inboxPreview(id, offset, PAGE_SIZE, signal), [id, query, searchDate, offset])
  const rows = useRequest(showSaved ? null : loadRows)
  const loadDetail = useCallback((signal) => api.message(id, selected.doc_id, signal), [id, selected])
  const detail = useRequest(selected && typeof selected.text !== 'string' ? loadDetail : null)

  useEffect(() => {
    if (selected && window.matchMedia('(max-width: 1070px)').matches) panelRef.current?.focus()
  }, [selected])

  function changePage(nextOffset) {
    setSelected(null)
    setOffset(nextOffset)
    listRef.current?.scrollTo({ top: 0 })
  }

  function search(value) {
    const next = value.trim()
    if (!next) return
    setDraft(next)
    setShowSaved(false)
    if (next === query) rows.retry()
    setQuery(next)
    changePage(0)
  }

  function clearSearch() {
    setDraft('')
    setQuery('')
    setDate('')
    changePage(0)
  }

  const closeLetter = useCallback(() => {
    setSelected(null)
    requestAnimationFrame(() => openButton.current?.focus({ preventScroll: true }))
  }, [])

  useEffect(() => {
    if (!selected) return
    function handleClose(event) {
      if (event.key === 'Escape' && !event.defaultPrevented && !event.target.matches?.('input, select')) closeLetter()
    }
    window.addEventListener('keydown', handleClose)
    return () => window.removeEventListener('keydown', handleClose)
  }, [selected, closeLetter])

  function toggleSaved(letter) {
    const nextSaved = saved.some((item) => item.doc_id === letter.doc_id)
      ? saved.filter((item) => item.doc_id !== letter.doc_id)
      : [savedSummary(letter), ...saved]
    setStorageFailed(!saveLetters(id, nextSaved))
    setSaved(nextSaved)
  }

  const items = showSaved ? saved : (rows.data?.results ?? rows.data?.messages ?? [])
  const total = rows.data?.total ?? mailbox.count
  const count = rows.data?.count
  const receivedOn = rows.data?.received_on
  const order = showSaved ? 'Недавно сохранённые' : query ? 'По релевантности' : 'Сначала новые'
  const title = showSaved ? 'Избранное' : query ? 'Результаты поиска' : 'Входящие'
  const showCount = showSaved || !query || rows.status === 'ready'
  const visibleCount = showSaved ? saved.length : query ? count : total

  return (
    <div className={selected ? 'mail-view has-letter' : 'mail-view'}>
      <SearchPanel draft={draft} setDraft={setDraft} onSearch={search} />
      <div className={`workspace${selected ? ' letter-visible' : ''}`}>
        <section className="panel inbox" aria-labelledby="inbox-heading">
          <div className="inbox-heading">
            <div className="title-row">
              <h2 id="inbox-heading">{title}</h2>
              {showCount && <span className="count">{number.format(visibleCount)}</span>}
            </div>
            <div className="list-controls">
              <button
                className="saved-toggle"
                onClick={() => { setShowSaved(!showSaved); setSelected(null) }}
                aria-pressed={showSaved}
              >
                <Bookmark size={16} /> {showSaved ? (query ? 'К результатам' : 'К входящим') : 'Избранное'}
              </button>
              {!showSaved && query && <button className="quiet reset-search" onClick={clearSearch}><X size={15} /> Сбросить поиск</button>}
              {!showSaved && <div className="date-filter">
                <label htmlFor="query-date" title="Последний доступный день и дата отсчёта для «вчера»">
                  <CalendarDays size={16} /><span>Поиск до</span>
                </label>
                <input
                  id="query-date"
                  type="date"
                  aria-label="Искать письма до даты включительно"
                  value={date}
                  onInput={(event) => {
                    setDate(event.target.value)
                    if (query) setSelected(null)
                  }}
                />
                {date && <button className="icon-button" aria-label="Убрать ограничение по дате" onClick={() => { setDate(''); if (query) setSelected(null) }}><X size={15} /></button>}
              </div>}
            </div>
          </div>
          <div className="list-meta">
            <span>{!showSaved && query ? <span className="active-query" title={query}>«{query}»</span> : 'Отправитель и тема'}</span>
            <span>{order}</span>
          </div>
          {receivedOn && <div className="parsed-date"><CalendarDays size={15} /> Получено {mailDate(receivedOn, true)}</div>}
          {storageFailed && <div className="storage-state" role="status">Браузер заблокировал сохранение. Избранное доступно до обновления страницы.</div>}
          <div className="mail-list" ref={listRef} aria-busy={rows.status === 'loading'}>
            {rows.status === 'loading' && <Notice icon={LoaderCircle} title={query ? 'Ищем письма' : 'Загружаем письма'} />}
            {rows.status === 'error' && <Notice title={query ? 'Поиск не удался' : 'Письма не загрузились'} action={rows.retry} actionText="Повторить">Проверьте подключение к API.</Notice>}
            {rows.status === 'ready' && !items.length && (
              <Notice icon={query ? Search : Inbox} title={query ? 'Совпадений пока нет' : 'Ящик пуст'}>
                {query && (date ? 'Попробуйте изменить запрос или дату.' : 'Попробуйте переформулировать запрос.')}
              </Notice>
            )}
            {showSaved && items.length === 0 && (
              <Notice icon={Bookmark} title="Избранное пусто">Откройте письмо и нажмите значок закладки, чтобы вернуться к нему позже.</Notice>
            )}
            {items.length > 0 && (
              <ul>{items.map((item) => (
                <MailRow
                  key={item.doc_id}
                  item={item}
                  selected={item.doc_id === selected?.doc_id}
                  onOpen={(event) => { openButton.current = event.currentTarget; setSelected(item) }}
                />
              ))}</ul>
            )}
          </div>
          {!query && rows.status === 'ready' && total > PAGE_SIZE && (
            <div className="pagination" aria-label="Страницы входящих">
              <span>{number.format(offset + 1)}–{number.format(offset + items.length)} из {number.format(total)}</span>
              <div>
                <button className="icon-button" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => changePage(offset - PAGE_SIZE)}><ChevronLeft size={17} /></button>
                <button className="icon-button" aria-label="Следующая страница" disabled={offset + items.length >= total} onClick={() => changePage(offset + PAGE_SIZE)}><ChevronRight size={17} /></button>
              </div>
            </div>
          )}
          {!showSaved && query && count === SEARCH_LIMIT && <div className="pagination">Показано до {SEARCH_LIMIT} результатов</div>}
        </section>
        <Reader
          selected={selected}
          detail={detail}
          onClose={closeLetter}
          panelRef={panelRef}
          saved={saved.some((item) => item.doc_id === selected?.doc_id)}
          onSave={toggleSaved}
        />
      </div>
    </div>
  )
}

function App() {
  const health = useRequest(api.health)
  const mailboxes = useRequest(api.mailboxes)
  const [active, setActive] = useState('')
  const boxes = (mailboxes.data?.mailboxes ?? []).slice().sort((a, b) => b.count - a.count || a.synthetic_user.localeCompare(b.synthetic_user))
  const current = boxes.find((box) => box.synthetic_user === active) ?? boxes[0]

  return (
    <div className="app">
      <a className="skip-link" href="#mail-main">К почте</a>
      <Sidebar boxes={boxes} active={current?.synthetic_user || ''} health={health} onChange={setActive} />
      <main className="main" id="mail-main">
        {current ? <Workspace key={current.synthetic_user} mailbox={current} /> : (
          <section className="panel service-state" aria-label="Состояние почты">
            {mailboxes.status === 'loading' && <Notice icon={LoaderCircle} title="Подключаемся к почте" />}
            {mailboxes.status === 'error' && (
              <Notice icon={Mail} title="Не удалось загрузить ящики" action={() => { mailboxes.retry(); health.retry() }} actionText="Повторить подключение">
                Проверьте, что бэкенд запущен и адрес VITE_API_BASE_URL доступен из браузера.
              </Notice>
            )}
            {mailboxes.status === 'ready' && <Notice title="Почтовых ящиков пока нет" />}
          </section>
        )}
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
