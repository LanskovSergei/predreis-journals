import { MedicineBoxOutlined, ToolOutlined } from '@ant-design/icons'

export const JOURNAL_CONFIG = {
  medical: { 
    title: 'Медосмотры', 
    icon: <MedicineBoxOutlined />, 
    add: 'Добавить медосмотр' 
  },
  technical: { 
    title: 'Техконтроль', 
    icon: <ToolOutlined />, 
    add: 'Добавить техконтроль' 
  },
} as const
