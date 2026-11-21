const apiBase = (import.meta.env.VITE_API_BASE_URL?.trim() || 'http://localhost:8000').replace(/\/+$/, '')

async function request(path, { signal, body } = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    signal,
    ...(body && {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`)
    error.status = response.status
    throw error
  }
  return response.json()
}

function mailboxPath(mailbox) {
  return `/mailboxes/${encodeURIComponent(mailbox)}/messages`
}

export const api = {
  health: (signal) => request('/health', { signal }),
  mailboxes: (signal) => request('/mailboxes', { signal }),
  inbox: (mailbox, offset, limit, signal) =>
    request(`${mailboxPath(mailbox)}?offset=${offset}&limit=${limit}`, { signal }),
  inboxPreview: (mailbox, offset, limit, signal) =>
    request(`${mailboxPath(mailbox)}?offset=${offset}&limit=${limit}&preview=true`, { signal }),
  search: (mailbox, query, date, limit, signal) => request('/search', {
    signal,
    body: { synthetic_user: mailbox, query, query_date: date || null, limit },
  }),
  async message(mailbox, id, signal) {
    try {
      return await request(`${mailboxPath(mailbox)}/${encodeURIComponent(id)}`, { signal })
    } catch (error) {
      if (error.status !== 404 && error.status !== 405) throw error
    }

    // Older API versions expose full texts only through the paginated inbox.
    const limit = 100
    for (let offset = 0; ; offset += limit) {
      const page = await api.inbox(mailbox, offset, limit, signal)
      const match = page.messages.find((message) => message.doc_id === id)
      if (match) return match
      if (!page.messages.length || offset + limit >= page.total) throw new Error('Message not found')
    }
  },
}
