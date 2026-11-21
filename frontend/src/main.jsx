import { useCallback, useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import {
  Archive, Bookmark, CalendarDays, Check, ChevronDown, ChevronLeft, ChevronRight, Inbox,
  LoaderCircle, Mail, MailOpen, Search, X,
} from 'lucide-react'
import '@fontsource-variable/inter'
import { api } from './api'
import { initials, mailContent, mailDate, number, preview } from './mail'
import { loadSaved, saveLetters, savedSummary } from './saved'
import { loadMailboxState, saveMailboxState } from './mailboxState'
import './style.css'

const DEFAULT_PAGE_SIZE = 20
const PAGE_SIZES = [20, 50, 100]
const SEARCH_LIMIT = 50
const SYNTHETIC_DEMO = import.meta.env.VITE_DEMO_MODE === 'synthetic'

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

function Header() {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand">
          <span className="brand-icon"><Mail aria-hidden="true" size={21} strokeWidth={1.75} /></span>
          <span>Почта</span>
        </div>
      </div>
    </header>
  )
}

function SearchPanel({ draft, setDraft, onSearch, onReveal }) {
  const inputRef = useRef(null)

  useEffect(() => {
    function focusSearch(event) {
      const key = event.key.toLowerCase()
      const searchKey = event.code === 'KeyK' || event.code === 'KeyL' || key === 'л' || key === 'l'
      if (!searchKey || !(event.metaKey || event.ctrlKey)) return
      event.preventDefault()
      onReveal()
      requestAnimationFrame(() => inputRef.current?.focus())
    }
    window.addEventListener('keydown', focusSearch)
    return () => window.removeEventListener('keydown', focusSearch)
  }, [onReveal])

  return (
    <section className="search-panel" aria-label="Поиск по почте">
      <div className="search-content">
        <form className="search-form" role="search" onSubmit={(event) => { event.preventDefault(); onSearch(draft) }}>
          <Search size={21} className="search-icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            aria-label="Поиск по письмам"
            placeholder="Поиск по почте"
            maxLength={1000}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ + Л' : 'Ctrl + Л'}</kbd>
          <button type="submit" disabled={!draft.trim()}>Найти</button>
        </form>
      </div>
    </section>
  )
}

function dateToIso(value) {
  return `${value.getUTCFullYear()}-${String(value.getUTCMonth() + 1).padStart(2, '0')}-${String(value.getUTCDate()).padStart(2, '0')}`
}

function dateFromIso(value) {
  return value ? new Date(`${value}T00:00:00Z`) : null
}

const ruDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
const ruMonth = new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' })
const weekDays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function DatePicker({ date, onChange }) {
  const [open, setOpen] = useState(false)
  const [month, setMonth] = useState(() => {
    const initial = dateFromIso(date) || new Date()
    return new Date(Date.UTC(initial.getUTCFullYear(), initial.getUTCMonth(), 1))
  })
  const pickerRef = useRef(null)
  const selected = dateFromIso(date)
  const todayIso = dateToIso(new Date())

  useEffect(() => {
    if (selected) setMonth(new Date(Date.UTC(selected.getUTCFullYear(), selected.getUTCMonth(), 1)))
  }, [date])

  useEffect(() => {
    if (!open) return undefined
    function closeOnOutside(event) {
      if (event.key === 'Escape' || (event.type === 'pointerdown' && !pickerRef.current?.contains(event.target))) setOpen(false)
    }
    window.addEventListener('keydown', closeOnOutside)
    window.addEventListener('pointerdown', closeOnOutside)
    return () => {
      window.removeEventListener('keydown', closeOnOutside)
      window.removeEventListener('pointerdown', closeOnOutside)
    }
  }, [open])

  const offset = (month.getUTCDay() + 6) % 7
  const firstDay = new Date(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1 - offset))
  const days = Array.from({ length: 42 }, (_, index) => new Date(firstDay.getTime() + index * 86400000))

  function shiftMonth(delta) {
    setMonth((current) => new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + delta, 1)))
  }

  function choose(value) {
    onChange(value)
    setOpen(false)
  }

  return (
    <div className="date-picker" ref={pickerRef}>
      <button
        type="button"
        className="date-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <CalendarDays size={16} aria-hidden="true" />
        <span>{date ? `До ${ruDate.format(selected)}` : 'Любая дата'}</span>
      </button>
      {date && <button type="button" className="date-clear" aria-label="Убрать ограничение по дате" onClick={() => onChange('')}><X size={15} /></button>}
      {open && (
        <div className="calendar-popover" role="dialog" aria-label="Выбор даты">
          <div className="calendar-heading">
            <button type="button" className="calendar-arrow" aria-label="Предыдущий месяц" onClick={() => shiftMonth(-1)}><ChevronLeft size={18} /></button>
            <strong>{ruMonth.format(month)}</strong>
            <button type="button" className="calendar-arrow" aria-label="Следующий месяц" onClick={() => shiftMonth(1)}><ChevronRight size={18} /></button>
          </div>
          <div className="calendar-grid calendar-weekdays" aria-hidden="true">
            {weekDays.map((day) => <span key={day}>{day}</span>)}
          </div>
          <div className="calendar-grid">
            {days.map((day) => {
              const value = dateToIso(day)
              const outsideMonth = day.getUTCMonth() !== month.getUTCMonth()
              const classes = ['calendar-day', outsideMonth && 'is-outside', value === date && 'is-selected', value === todayIso && 'is-today'].filter(Boolean).join(' ')
              return <button type="button" className={classes} key={value} aria-label={ruDate.format(day)} aria-pressed={value === date} onClick={() => choose(value)}>{day.getUTCDate()}</button>
            })}
          </div>
          <div className="calendar-footer">
            <button type="button" onClick={() => choose(todayIso)}>Сегодня</button>
            <button type="button" onClick={() => { onChange(''); setOpen(false) }}>Очистить</button>
          </div>
        </div>
      )}
    </div>
  )
}

function Sidebar({ mailbox, boxes, onMailbox, folder, setFolder, folderCounts }) {
  const index = boxes.indexOf(mailbox)
  const [mailboxMenuOpen, setMailboxMenuOpen] = useState(false)
  const switcherRef = useRef(null)
  const switcherButton = useRef(null)

  useEffect(() => {
    if (!mailboxMenuOpen) return undefined
    function dismiss(event) {
      if (event.key === 'Escape') {
        setMailboxMenuOpen(false)
        requestAnimationFrame(() => switcherButton.current?.focus())
      } else if (event.type === 'pointerdown' && !switcherRef.current?.contains(event.target)) {
        setMailboxMenuOpen(false)
      }
    }
    document.addEventListener('keydown', dismiss)
    document.addEventListener('pointerdown', dismiss)
    return () => {
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('pointerdown', dismiss)
    }
  }, [mailboxMenuOpen])

  return (
    <aside className="mail-sidebar" aria-label="Навигация по почте">
      <div className="sidebar-brand">
        <span className="brand-icon"><Mail aria-hidden="true" size={20} strokeWidth={1.8} /></span>
        <span>Почта</span><span className="vk-brand">vk</span>
      </div>
      {SYNTHETIC_DEMO && <p className="demo-banner">Демо: здесь синтетические письма</p>}
      <div className="mailbox-switcher" ref={switcherRef}>
        <button
          ref={switcherButton}
          type="button"
          className="sidebar-account"
          aria-haspopup="listbox"
          aria-expanded={mailboxMenuOpen}
          onClick={() => setMailboxMenuOpen((open) => !open)}
        >
          <span className="account-avatar">{String(index + 1).padStart(2, '0')}</span>
          <span className="account-details"><strong>Ящик {index + 1}</strong><small>{number.format(mailbox.count)} писем</small></span>
          <ChevronDown size={16} className={`account-chevron ${mailboxMenuOpen ? 'is-open' : ''}`} aria-hidden="true" />
        </button>
        {mailboxMenuOpen && (
          <div className="mailbox-menu" role="listbox" aria-label="Почтовые ящики">
            <div className="mailbox-menu-heading">
              <strong>Почтовые ящики</strong>
              <span>{boxes.length} ящиков</span>
            </div>
            <div className="mailbox-option-list">
              {boxes.map((box, position) => {
                const active = box.synthetic_user === mailbox.synthetic_user
                return (
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    className={`mailbox-option ${active ? 'is-selected' : ''}`}
                    key={box.synthetic_user}
                    onClick={() => {
                      onMailbox(box.synthetic_user)
                      setMailboxMenuOpen(false)
                    }}
                  >
                    <span className="mailbox-option-number">{String(position + 1).padStart(2, '0')}</span>
                    <span className="mailbox-option-details"><strong>Ящик {position + 1}</strong><small>{number.format(box.count)} писем</small></span>
                    {active && <Check size={17} className="mailbox-option-check" aria-hidden="true" />}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
      <div className="sidebar-caption">ПАПКИ</div>
      {[['inbox','Входящие',Inbox],['all','Вся почта',Mail],['starred','Помеченные',Bookmark],['important','Важные',Archive],['spam','Спам',MailOpen],['trash','Корзина',X]].map(([key,label,Icon]) => <button key={key} className={`sidebar-item ${folder===key?'is-active':''}`} onClick={() => setFolder(key)}><Icon size={18}/><span>{label}</span>{folderCounts[key]>0&&<span className="sidebar-count">{number.format(folderCounts[key])}</span>}</button>)}
    </aside>
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

function MailRow({ item, onOpen, state, onSelect, onStar }) {
  const content = mailContent(item)
  return (
    <li>
      <div className={`mail-row ${state?.read ? 'is-read' : ''}`}>
        <input className="mail-check" type="checkbox" checked={!!state?.selected} onChange={onSelect} aria-label={`Выбрать: ${content.subject}`} />
        <button type="button" className="row-star" aria-label="Пометить избранным" onClick={onStar}><Bookmark size={18} fill={state?.starred ? 'currentColor' : 'none'} /></button>
        <button type="button" className="row-open" aria-haspopup="dialog" onClick={onOpen}>
        <SenderMark content={content} />
        <span className="row-content">
          <strong className="row-subject">{content.subject}</strong>
          <span className="row-snippet">{preview(content.text) || 'Письмо без текста'}</span>
          <span className="sender">{content.sender}</span>
        </span>
        <span className="row-date">{mailDate(item.date)}</span>
        </button>
      </div>
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
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE)
  const [selected, setSelected] = useState(null)
  const [showSaved, setShowSaved] = useState(false)
  const [folder, setFolder] = useState('inbox')
  const [category, setCategory] = useState('primary')
  const [sortOrder, setSortOrder] = useState('newest')
  const [mailState, setMailState] = useState(() => loadMailboxState(id))
  const [selectedIds, setSelectedIds] = useState([])
  const [saved, setSaved] = useState(() => loadSaved(id))
  const [storageFailed, setStorageFailed] = useState(false)
  const listHeading = useRef(null)
  const openButton = useRef(null)
  const lastInboxPage = useRef(null)

  const searchDate = query ? date : ''
  useEffect(() => {
    const next = draft.trim()
    const timer = window.setTimeout(() => {
      const nextQuery = next.length >= 2 ? next : ''
      setShowSaved(false)
      setOffset(0)
      setQuery((current) => current === nextQuery ? current : nextQuery)
    }, 320)
    return () => window.clearTimeout(timer)
  }, [draft])
  const loadRows = useCallback((signal) => query
    ? api.search(id, query, searchDate, SEARCH_LIMIT, signal)
    : api.inboxPreview(id, offset, pageSize, signal, date), [id, query, searchDate, offset, pageSize, date])
  const rows = useRequest(showSaved ? null : loadRows)
  useEffect(() => {
    if (!query && !showSaved && rows.status === 'ready') lastInboxPage.current = rows.data
  }, [query, showSaved, rows.status, rows.data])
  const loadDetail = useCallback((signal) => api.message(id, selected.doc_id, signal), [id, selected])
  const detail = useRequest(selected && typeof selected.text !== 'string' ? loadDetail : null)

  function changePage(nextOffset) {
    setSelected(null)
    setOffset(nextOffset)
    listHeading.current?.scrollIntoView({ block: 'nearest' })
  }

  function changePageSize(nextPageSize) {
    setOffset(0)
    setPageSize(nextPageSize)
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

  const searchHasNoHits = Boolean(query && rows.status === 'ready' && (rows.data?.count ?? rows.data?.results?.length ?? 0) === 0 && lastInboxPage.current)
  const rawItems = showSaved ? saved : searchHasNoHits
    ? (lastInboxPage.current?.messages ?? lastInboxPage.current?.results ?? [])
    : (rows.data?.results ?? rows.data?.messages ?? [])
  const classify = (item) => { const c=mailContent(item); const text=`${c.sender} ${c.subject} ${c.text}`.toLowerCase(); return /скидк|акци|промокод|распродаж|предложени/.test(text)?'promo':/vk|вконтакте|telegram|facebook|социальн/.test(text)?'social':/уведом|оповещ|код подтверж|security|безопасност/.test(text)?'notice':'primary' }
  const items = rawItems.filter((item) => { const s=mailState[item.doc_id]||{}; if(folder==='inbox' && (s.spam||s.deleted||s.archived)) return false; if(folder==='spam'&&!s.spam)return false; if(folder==='trash'&&!s.deleted)return false; if(folder==='important'&&!s.important)return false; if(folder==='starred'&&!s.starred&&!saved.some(x=>x.doc_id===item.doc_id))return false; if(folder==='all'&&(s.spam||s.deleted))return false; return (query && !searchHasNoHits) || folder!=='inbox' || classify(item)===category }).slice().sort((a,b)=>sortOrder==='oldest'?new Date(a.date)-new Date(b.date):new Date(b.date)-new Date(a.date))
  function patchState(ids, patch) { const next={...mailState}; ids.forEach((doc)=>{next[doc]={...(next[doc]||{}),...patch}}); setMailState(next); saveMailboxState(id,next) }
  function toggleSelect(doc) { setSelectedIds((current)=>current.includes(doc)?current.filter(x=>x!==doc):[...current,doc]) }
  const states=Object.values(mailState)
  const folderCounts={inbox:Math.max(0,mailbox.count-states.filter(s=>s.spam||s.deleted||s.archived).length),all:Math.max(0,mailbox.count-states.filter(s=>s.spam||s.deleted).length),starred:Object.keys(mailState).filter(key=>mailState[key].starred).length+saved.filter(letter=>!mailState[letter.doc_id]?.starred).length,important:states.filter(s=>s.important&&!s.spam&&!s.deleted).length,spam:states.filter(s=>s.spam&&!s.deleted).length,trash:states.filter(s=>s.deleted).length}
  const position = selected ? items.findIndex((item) => item.doc_id === selected.doc_id) : -1
  const total = rows.data?.total ?? mailbox.count
  const count = rows.data?.count
  const receivedOn = rows.data?.received_on
  const title = query ? 'Результаты поиска' : ({inbox:'Входящие',all:'Вся почта',starred:'Помеченные',important:'Важные',spam:'Спам',trash:'Корзина'}[folder] || 'Входящие')
  const showCount = showSaved || !query || rows.status === 'ready'
  const visibleCount = showSaved ? saved.length : searchHasNoHits ? (lastInboxPage.current?.total ?? items.length) : query ? count : total
  function changeDate(nextDate) {
    setDate(nextDate)
    setOffset(0)
  }

  return (
    <>
      <main className="main" id="mail-main">
        <Sidebar mailbox={mailbox} boxes={boxes} onMailbox={onMailbox} folder={folder} setFolder={(v)=>{setFolder(v);setShowSaved(false);setSelectedIds([])}} folderCounts={folderCounts} />
        <div className="mail-workspace">
        <SearchPanel draft={draft} setDraft={setDraft} onSearch={search} onReveal={revealSearch} />
        <section className="inbox" aria-labelledby="inbox-heading">
          <div className="inbox-heading">
            <div className="title-row">
              <h2 id="inbox-heading" ref={listHeading} tabIndex={-1}>{title}</h2>
              {showCount && <span className="count">{number.format(visibleCount)}</span>}
            </div>
            {!showSaved && (
              <div className="list-controls">
                {!query && <label className="page-size"><span>На странице</span><select value={pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>{PAGE_SIZES.map((size) => <option value={size} key={size}>{size}</option>)}</select></label>}
                {!query && <label className="page-size"><span>Сначала</span><select value={sortOrder} onChange={(event)=>setSortOrder(event.target.value)}><option value="newest">новые</option><option value="oldest">старые</option></select></label>}
                {query && <button className="quiet" onClick={clearSearch}><X size={15} /> Сбросить</button>}
                <DatePicker date={date} onChange={changeDate} />
              </div>
            )}
          </div>
          {!query && !showSaved && <div className="category-tabs">{[['primary','Основные'],['promo','Промоакции'],['social','Соцсети'],['notice','Оповещения']].map(([key,label])=><button key={key} className={category===key?'active':''} onClick={()=>setCategory(key)}>{label}</button>)}</div>}
          {selectedIds.length>0&&<div className="bulk-toolbar"><span>Выбрано: {selectedIds.length}</span><button onClick={()=>{patchState(selectedIds,{read:true});setSelectedIds([])}}>Прочитано</button><button onClick={()=>{patchState(selectedIds,{important:true});setSelectedIds([])}}>Важное</button><button onClick={()=>{patchState(selectedIds,{spam:folder!=='spam'});setSelectedIds([])}}>{folder==='spam'?'Не спам':'Спам'}</button><button onClick={()=>{patchState(selectedIds,{deleted:folder!=='trash'});setSelectedIds([])}}>{folder==='trash'?'Восстановить':'Удалить'}</button><button onClick={()=>setSelectedIds([])}>Снять выбор</button></div>}
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
            {rows.status === 'ready' && !items.length && !searchHasNoHits && (
              <Notice icon={query ? Search : Inbox} title={query ? 'Совпадений пока нет' : 'Ящик пуст'}>
                {query && (date ? 'Попробуйте изменить запрос или дату.' : 'Попробуйте переформулировать запрос.')}
              </Notice>
            )}
            {showSaved && items.length === 0 && (
              <Notice icon={Bookmark} title="Избранное пусто">Откройте письмо и нажмите значок закладки, чтобы вернуться к нему позже.</Notice>
            )}
            {items.length > 0 && (
              <ul>{items.map((item) => (
                <MailRow key={item.doc_id} item={item} state={{...(mailState[item.doc_id]||{}),selected:selectedIds.includes(item.doc_id)}} onSelect={()=>toggleSelect(item.doc_id)} onStar={()=>patchState([item.doc_id],{starred:!(mailState[item.doc_id]?.starred)})} onOpen={(event) => { openButton.current = event.currentTarget; patchState([item.doc_id],{read:true}); setSelected(item) }} />
              ))}</ul>
            )}
          </div>
          {!query && rows.status === 'ready' && total > 0 && (
            <div className="pagination" aria-label="Страницы входящих">
              <span className="pagination-summary">{number.format(offset + 1)}–{number.format(offset + items.length)} из {number.format(total)}</span>
              <div>
                <button className="icon-button" aria-label="Предыдущая страница" disabled={offset === 0} onClick={() => changePage(offset - pageSize)}><ChevronLeft size={18} /></button>
                <button className="icon-button" aria-label="Следующая страница" disabled={offset + items.length >= total} onClick={() => changePage(offset + pageSize)}><ChevronRight size={18} /></button>
              </div>
            </div>
          )}
          {!showSaved && query && count === SEARCH_LIMIT && <div className="pagination">Показано до {SEARCH_LIMIT} результатов</div>}
        </section>
        </div>
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
