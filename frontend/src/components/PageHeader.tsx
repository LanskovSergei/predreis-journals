import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'

/** Заголовок страницы — как OrgPageHeader у платформы. */
export function PageHeader({ title, subtitle, extra }: { title: string; subtitle?: string; extra?: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
      <div style={{ minWidth: 0 }}>
        <Typography.Title level={4} style={{ marginBottom: 4 }}>
          {title}
        </Typography.Title>
        {subtitle ? (
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0, maxWidth: 720 }}>
            {subtitle}
          </Typography.Paragraph>
        ) : null}
      </div>
      {extra ? <Space wrap>{extra}</Space> : null}
    </div>
  )
}
