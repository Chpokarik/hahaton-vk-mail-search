const field = {
  from: /^[ \t]*(?:от|from)[ \t]*[:：][ \t]*(.*)$/im,
  subject: /^[ \t]*(?:тема|subject)[ \t]*[:：][ \t]*(.*)$/im,
  body: /^[ \t]*(?:текст письма|body)[ \t]*[:：][ \t]*/im,
}

export function mailContent(mail) {
  const raw = (mail.text ?? mail.snippet ?? '').replace(/\r\n?/g, '\n')
  const body = raw.match(field.body)
  const header = body ? raw.slice(0, body.index) : raw
  const from = header.match(field.from)
  const subject = header.match(field.subject)
  const title = mail.subject?.trim() || subject?.[1].trim() || 'Без темы'
  const text = (body
    ? raw.slice(body.index + body[0].length)
    : raw.replace(field.from, '').replace(field.subject, '')).trim()
  // Some corpus entries store both the subject and the body on one line.
  const inline = !body && !text && title.length > 140
    ? subject?.[1].trim().match(/^(.{1,105}?)\.[ \t]+(.+)$/u)
    : null
  const sender = mail.sender || from?.[1].trim()
  return {
    sender: sender || 'Без отправителя',
    hasSender: Boolean(sender),
    subject: inline?.[1] || title,
    text: inline?.[2] || text || (body ? '' : raw.trim()),
  }
}

export function preview(text) {
  const line = text.replace(/\s+/g, ' ')
  return line.length > 170 ? `${line.slice(0, 167).replace(/\s+\S*$/, '')}…` : line
}

export function initials(name) {
  return name.match(/[\p{L}\d]+/gu)?.slice(0, 2).map((word) => word[0].toUpperCase()).join('') || '?'
}

export function colorIndex(value) {
  return [...value].reduce((sum, character) => sum + character.codePointAt(0), 0) % 5
}

const dateFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
const fullDateFormat = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
export const number = new Intl.NumberFormat('ru-RU')

export function mailDate(value, full = false) {
  const date = value && new Date(value)
  return date && Number.isFinite(date.getTime())
    ? (full ? fullDateFormat : dateFormat).format(date).replace(/ г\.$/, '')
    : 'Дата неизвестна'
}

