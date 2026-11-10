import { App as AntApp, ConfigProvider } from 'antd'
import ruRU from 'antd/locale/ru_RU'
import { AuthProvider } from './core/auth/AuthProvider'
import { AppRouter } from './core/router/AppRouter'
import { antdTheme } from './core/theme/antdTheme'
import './core/styles/global.css'

export default function App() {
  return (
    <ConfigProvider theme={antdTheme} locale={ruRU}>
      <AntApp>
        <AuthProvider>
          <AppRouter />
        </AuthProvider>
      </AntApp>
    </ConfigProvider>
  )
}
