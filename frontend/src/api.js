const configuredOrigin = import.meta.env.VITE_API_URL?.trim().replace(/\/+$/, '')
const apiOrigin = configuredOrigin || (
  import.meta.env.PROD ? 'https://diseasescope-2.onrender.com' : ''
)

export const API_BASE = `${apiOrigin}/api`
