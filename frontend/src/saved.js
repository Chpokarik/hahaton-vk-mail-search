import { mailContent, preview } from './mail'

const STORAGE_KEY = 'vk-mail:saved:'

export function loadSaved(mailbox) {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY + mailbox) || '[]')
    return Array.isArray(stored) ? stored : []
  } catch {
    return []
  }
}

export function saveLetters(mailbox, letters) {
  try {
    localStorage.setItem(STORAGE_KEY + mailbox, JSON.stringify(letters))
    return true
  } catch {
    return false
  }
}

export function savedSummary(letter) {
  const { subject, text, sender, hasSender } = mailContent(letter)
  return {
    doc_id: letter.doc_id,
    date: letter.date,
    subject,
    snippet: preview(text),
    sender: hasSender ? sender : null,
  }
}
