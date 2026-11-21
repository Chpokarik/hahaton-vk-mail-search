const PREFIX = 'vk-mail:state:'

export function loadMailboxState(mailbox) {
  try { return JSON.parse(localStorage.getItem(PREFIX + mailbox) || '{}') } catch { return {} }
}

export function saveMailboxState(mailbox, state) {
  try { localStorage.setItem(PREFIX + mailbox, JSON.stringify(state)); return true } catch { return false }
}
