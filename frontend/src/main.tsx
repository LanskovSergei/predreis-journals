import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import App from './App.tsx'

// Как у платформы: русская локаль dayjs задаёт понедельник первым днём недели в календарях
dayjs.locale('ru')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
