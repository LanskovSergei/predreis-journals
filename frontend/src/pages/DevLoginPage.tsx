import { useState } from 'react'
import { App, Button, Card, Flex, Form, Input, Typography } from 'antd'
import { devLogin } from '@/api/journals'
import { errorMessage } from '@/api/client'
import { session } from '@/auth/session'

/** Вход для стенда разработчика. В бою вход только через платформу (общий токен). */
export function DevLoginPage() {
  const { message } = App.useApp()
  const [busy, setBusy] = useState(false)

  const submit = async (values: { email: string; password: string }) => {
    setBusy(true)
    try {
      session.setTokens(await devLogin(values.email, values.password))
      window.location.assign('/journals/')
    } catch (err) {
      message.error(errorMessage(err, 'Не удалось войти'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Flex align="center" justify="center" style={{ minHeight: '100vh', padding: 16 }}>
      <Card style={{ width: 380, maxWidth: '100%' }}>
        <Typography.Title level={4}>Вход в журналы</Typography.Title>
        <Typography.Paragraph type="secondary">Стенд разработчика: почта и пароль пользователя ПРЕДРЕЙС.</Typography.Paragraph>
        <Form layout="vertical" onFinish={(v) => void submit(v)}>
          <Form.Item name="email" label="Почта" rules={[{ required: true, message: 'Введите почту' }]}>
            <Input autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="Пароль" rules={[{ required: true, message: 'Введите пароль' }]}>
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={busy}>
            Войти
          </Button>
        </Form>
      </Card>
    </Flex>
  )
}
