import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Bookmark, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Inbox,
  LoaderCircle, Mail, MailOpen, Search, X,
} from 'lucide-react'
import '@fontsource-variable/inter'
import { api } from './api'
import { initials, mailContent, mailDate, number, preview } from './mail'
import { loadSaved, saveLetters, savedSummary } from './saved'
import './style.css'

const PAGE_SIZE = 20
const SEARCH_LIMIT = 50
const SUGGESTIONS = ['Заказы от 20 ноября 2026', 'Счёт на оплату', 'Покупатель хочет вернуть товар']

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

  const current = !load
    ? { status: 'idle' }
    : state?.load === load && state.attempt === attempt ? state : { status: 'loading' }
  return { ...current, retry: () => retry((previous) => previous + 1) }
}

function Notice({ icon: Icon = Inbox, title, children, action, actionText }) {
  return (
    <div className="notice" role="status">
      <span className="notice-icon"><Icon size={23} strokeWidth={1.65} /></span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action && <button className="text-button" onClick={action}>{actionText}</button>}
    </div>
  )
}

function Header({ boxes = [], mailbox, onMailbox, showSaved, onInbox, onSaved, hasQuery }) {
  const index = boxes.indexOf(mailbox)
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand">
          <span className="brand-icon"><Mail aria-hidden="true" size={21} strokeWidth={1.75} /></span>
          <span>Почта</span>
        </div>
        {mailbox && (
          <>
            <nav className="site-nav" aria-label="Разделы почты">
              <button type="button" aria-current={!showSaved ? 'page' : undefined} onClick={onInbox}>
                <Inbox size={17} aria-hidden="true" /> {hasQuery ? 'Результаты' : 'Входящие'}
              </button>
              <button type="button" aria-current={showSaved ? 'page' : undefined} onClick={onSaved}>
                <Bookmark size={17} aria-hidden="true" /> Избранное
              </button>
            </nav>
            <label className="mailbox-picker">
              <span className="mailbox-monogram" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
              <span className="mailbox-label" aria-hidden="true">Ящик {index + 1}</span>
              <ChevronDown size={15} aria-hidden="true" />
              <select aria-label="Почтовый ящик" value={mailbox.synthetic_user} onChange={(event) => onMailbox(event.target.value)}>
                {boxes.map((box, position) => <option value={box.synthetic_user} key={box.synthetic_user}>Ящик {position + 1} · {box.synthetic_user}</option>)}
              </select>
            </label>
          </>
        )}
      </div>
    </header>
  )
}

function SearchPanel({ draft, setDraft, onSearch, onReveal }) {
  const inputRef = useRef(null)

  useEffect(() => {
    function focusSearch(event) {
      if (event.key.toLowerCase() !== 'k' || !(event.metaKey || event.ctrlKey)) return
      event.preventDefault()
      onReveal()
      requestAnimationFrame(() => inputRef.current?.focus())
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [onReveal])

  return (
    <section className="search-panel" aria-labelledby="search-heading">
      <div className="hero-image" aria-hidden="true" />
      <div className="search-content">
        <h1 id="search-heading">Найти письмо<span>.</span></h1>
        <p>Поиск по почте своими словами</p>
        <form className="search-form" role="search" onSubmit={(event) => { event.preventDefault(); onSearch(draft) }}>
          <Search size={21} className="search-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            aria-label="Поиск по письмам"
            placeholder="Например, заказы за вчера"
            maxLength={1000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K'}</kbd>
          <button type="submit" disabled={!draft.trim()}>Найти</button>
        </form>
        <div className="suggestions">
          {SUGGESTIONS.map((suggestion) => (
            <button type="button" key={suggestion} onClick={() => onSearch(suggestion)}>{suggestion}</button>
          ))}
        </div>
      </div>
    </section>
  )
}

function SenderMark({ content }) {
  const palette = content.hasSender ? (content.sender.codePointAt(content.sender.length - 1) || 0) % 4 : 0
  return (
    <span className={`sender-mark tone-${palette}`} aria-hidden="true">
      {content.hasSender ? initials(content.sender) : <Mail size={20} strokeWidth={1.65} />}
    </span>
  )
}

function MailRow({ item, onOpen }) {
  const content = mailContent(item)
  return (
    <li>
      <button type="button" className="mail-row" aria-haspopup="dialog" onClick={onOpen}>
        <SenderMark content={content} />
        <span className="row-content">
          <strong className="row-subject">{content.subject}</strong>
          <span className="row-snippet">{preview(content.text) || 'Письмо без текста'}</span>
          <span className="sender">{content.sender}</span>
        </span>
        <span className="row-date">{mailDate(item.date)}</span>
      </button>
    </li>
  )
}

function Reader({ selected, detail, onClose, saved, onSave, position, total, onStep }) {
  const dialogRef = useRef(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (selected && !dialog.open) dialog.showModal()
    if (!selected && dialog.open) dialog.close()
  }, [selected])

  const mail = typeof selected?.text === 'string' ? selected : detail.data
  const content = selected ? mailContent(mail || selected) : null

  return (
    <dialog
      ref={dialogRef}
      className="letter-drawer"
      aria-labelledby="letter-title"
      onCancel={(event) => { event.preventDefault(); onClose() }}
      onClick={(event) => { if (event.currentTarget === event.target) onClose() }}
    >
      {selected && (
        <div className="drawer-panel">
          <div className="reader-toolbar">
            {position >= 0 && total > 1 ? (
              <nav className="reader-navigation" aria-label="Листать письма">
                <button className="icon-button" disabled={position === 0} aria-label="Предыдущее письмо" onClick={() => onStep(-1)}><ChevronLeft size={20} /></button>
                <span>{position + 1} из {total}</span>
                <button className="icon-button" disabled={position + 1 === total} aria-label="Следующее письмо" onClick={() => onStep(1)}><ChevronRight size={20} /></button>
              </nav>
            ) : <span><Mail size={17} aria-hidden="true" /> Письмо</span>}
            <div className="reader-actions">
              <button className="icon-button save-button" onClick={() => onSave(mail || selected)} aria-pressed={saved} aria-label={saved ? 'Убрать из избранного' : 'Сохранить в избранное'} title={saved ? 'Убрать из избранного' : 'Сохранить в избранное'}>
                <Bookmark size={20} fill={saved ? 'currentColor' : 'none'} />
              </button>
              <button className="icon-button" onClick={onClose} aria-label="Закрыть письмо"><X size={21} /></button>
            </div>
          </div>
          <article className="letter" key={selected.doc_id}>
            <h2 id="letter-title">{content.subject}</h2>
            <div className="letter-meta">
              <SenderMark content={content} />
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
        </div>
      )}
    </dialog>
  )
}

function moveListFocus(event) {
  if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return
  const row = event.target.closest('.mail-row')?.parentElement
  if (!row) return
  const neighbor = event.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling
  event.preventDefault()
  neighbor?.querySelector('.mail-row')?.focus()
}

function Workspace({ mailbox, boxes, onMailbox }) {
  const id = mailbox.synthetic_user
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [date, setDate] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(null)
  const [showSaved, setShowSaved] = useState(false)
  const [saved, setSaved] = useState(() => loadSaved(id))
  const [storageFailed, setStorageFailed] = useState(false)
  const listHeading = useRef(null)
  const openButton = useRef(null)

  const searchDate = query ? date : ''
  const loadRows = useCallback((signal) => query
    ? api.search(id, query, searchDate, SEARCH_LIMIT, signal)
    : api.inboxPreview(id, offset, PAGE_SIZE, signal), [id, query, searchDate, offset])
  const rows = useRequest(showSaved ? null : loadRows)
  const loadDetail = useCallback((signal) => api.message(id, selected.doc_id, signal), [id, selected])
  const detail = useRequest(selected && typeof selected.text !== 'string' ? loadDetail : null)

  function changePage(nextOffset) {
    setSelected(null)
    setOffset(nextOffset)
    listHeading.current?.scrollIntoView({ block: 'nearest' })
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

  const revealSearch = useCallback(() => setSelected(null), [])

  function closeLetter() {
    setSelected(null)
    requestAnimationFrame(() => (openButton.current?.isConnected ? openButton.current : listHeading.current)?.focus({ preventScroll: true }))
  }

  function toggleSaved(letter) {
    const nextSaved = saved.some((item) => item.doc_id === letter.doc_id)
      ? saved.filter((item) => item.doc_id !== letter.doc_id)
      : [savedSummary(letter), ...saved]
    setStorageFailed(!saveLetters(id, nextSaved))
    setSaved(nextSaved)
  }

  const items = showSaved ? saved : (rows.data?.results ?? rows.data?.messages ?? [])
  const position = selected ? items.findIndex((item) => item.doc_id === selected.doc_id) : -1
  const total = rows.data?.total ?? mailbox.count
  const count = rows.data?.count
  const receivedOn = rows.data?.received_on
  const title = showSaved ? 'Избранное' : query ? 'Результаты поиска' : 'Входящие'
  const showCount = showSaved || !query || rows.status === 'ready'
  const visibleCount = showSaved ? saved.length : query ? count : total

  return (
    <>
      <Header
        boxes={boxes}
        mailbox={mailbox}
        onMailbox={onMailbox}
        showSaved={showSaved}
        onInbox={() => setShowSaved(false)}
        onSaved={() => setShowSaved(true)}
        hasQuery={Boolean(query)}
      />
      <main className="main" id="mail-main">
        <SearchPanel draft={draft} setDraft={setDraft} onSearch={search} onReveal={revealSearch} />
        <section className="inbox" aria-labelledby="inbox-heading">
          <div className="inbox-heading">
            <div className="title-row">
              <h2 id="inbox-heading" ref={listHeading} tabIndex={-1}>{title}</h2>
              {showCount && <span className="count">{number.format(visibleCount)}</span>}
            </div>
            {!showSaved && (
              <div className="list-controls">
                {query && <button className="quiet" onClick={clearSearch}><X size={15} /> Сбросить</button>}
                <div className="date-filter">
                  <label htmlFor="query-date" title="Последний доступный день и дата отсчёта для «вчера»">
                    <CalendarDays size={16} /><span>Поиск до</span>
                  </label>
                  <input
                    id="query-date"
                    type="date"
                    aria-label="Искать письма до даты включительно"
                    value={date}
                    onInput={(event) => setDate(event.target.value)}
                  />
                  {date && <button className="icon-button date-clear" aria-label="Убрать ограничение по дате" onClick={() => setDate('')}><X size={15} /></button>}
                </div>
              </div>
            )}
          </div>
          {!showSaved && query && (
            <div className="list-meta">
              <span className="active-query" title={query}>«{query}»</span>
              {receivedOn && <span className="parsed-date">Получено {mailDate(receivedOn, true)}</span>}
            </div>
          )}
          {storageFailed && <div className="storage-state" role="status">Браузер заблокировал сохранение. Избранное доступно до обновления страницы.</div>}
          <div className="mail-list" onKeyDown={moveListFocus} aria-busy={rows.status === 'loading'}>
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
                <MailRow key={item.doc_id} item={item} onOpen={(event) => { openButton.current = event.currentTarget; setSelected(item) }} />
              ))}</ul>
            )}
          </div>
          {!query && rows.status === 'ready' && total > PAGE_SIZE && (
            <div className="pagination" aria-label="Страницы входящих">
              <span>{number.format(offset + 1)}–{number.format(offset + items.length)} из {number.format(total)}</span>
              <div>
                <button className="icon-button" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => changePage(offset - PAGE_SIZE)}><ChevronLeft size={18} /></button>
                <button className="icon-button" aria-label="Следующая страница" disabled={offset + items.length >= total} onClick={() => changePage(offset + PAGE_SIZE)}><ChevronRight size={18} /></button>
              </div>
            </div>
          )}
          {!showSaved && query && count === SEARCH_LIMIT && <div className="pagination">Показано до {SEARCH_LIMIT} результатов</div>}
        </section>
      </main>
      <Reader
        selected={selected}
        detail={detail}
        onClose={closeLetter}
        saved={saved.some((item) => item.doc_id === selected?.doc_id)}
        onSave={toggleSaved}
        position={position}
        total={items.length}
        onStep={(direction) => setSelected(items[position + direction])}
      />
    </>
  )
}

function App() {
  const mailboxes = useRequest(api.mailboxes)
  const [active, setActive] = useState('')
  const boxes = (mailboxes.data?.mailboxes ?? []).slice().sort((a, b) => b.count - a.count || a.synthetic_user.localeCompare(b.synthetic_user))
  const current = boxes.find((box) => box.synthetic_user === active) ?? boxes[0]

  return (
    <div className="app">
      <a className="skip-link" href="#mail-main">К почте</a>
      {current ? <Workspace key={current.synthetic_user} mailbox={current} boxes={boxes} onMailbox={setActive} /> : (
        <>
          <Header />
          <main className="main service-state" id="mail-main">
            {mailboxes.status === 'loading' && <Notice icon={LoaderCircle} title="Подключаемся к почте" />}
            {mailboxes.status === 'error' && (
              <Notice icon={Mail} title="Не удалось загрузить ящики" action={mailboxes.retry} actionText="Повторить подключение">
                Проверьте подключение к серверу почты.
              </Notice>
            )}
            {mailboxes.status === 'ready' && <Notice title="Почтовых ящиков пока нет" />}
          </main>
        </>
      )}
    </div>
  )
}

createRoot(document.getElementById('root')).render(<App />)
