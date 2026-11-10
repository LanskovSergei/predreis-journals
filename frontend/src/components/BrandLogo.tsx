import { useState } from 'react'

/** Логотип платформы (файлы отдаёт фронтенд Предрейса с того же домена); без них — текстовый знак. */
export function BrandLogo({ collapsed }: { collapsed: boolean }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <span style={{ color: '#fff', fontWeight: 700, fontSize: collapsed ? 14 : 16, letterSpacing: 0.2 }}>
        {collapsed ? 'П' : 'Предрейс ONLINE'}
      </span>
    )
  }
  return (
    <img
      src={collapsed ? '/app-icon.png' : '/logo-predreis-online.png'}
      alt="Предрейс ONLINE"
      style={{ height: 40, width: 'auto', maxWidth: '100%', objectFit: 'contain', borderRadius: collapsed ? 10 : 0 }}
      draggable={false}
      onError={() => setFailed(true)}
    />
  )
}
