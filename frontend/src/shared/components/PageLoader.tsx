import { Flex, Spin } from 'antd'

export function PageLoader({ tip = 'Загрузка…', fullScreen = false }: { tip?: string; fullScreen?: boolean }) {
  return (
    <Flex align="center" justify="center" style={{ minHeight: fullScreen ? '100vh' : 240, width: '100%' }}>
      <Spin size="large" tip={tip}>
        <div style={{ width: 120, height: 60 }} />
      </Spin>
    </Flex>
  )
}
