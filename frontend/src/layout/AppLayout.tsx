import { useMemo, useState } from 'react'
import { Button, Dropdown, Grid, Layout, Menu, Typography, type MenuProps } from 'antd'
import {
  ArrowLeftOutlined,
  DashboardOutlined,
  LogoutOutlined,
  MedicineBoxOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SettingOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { goToLogin, goToPlatform, session } from '@/auth/session'
import { BrandLogo } from '@/components/BrandLogo'
import { brandColors } from '@/theme/antdTheme'
import { roleLabels } from '@/utils/labels'
import styles from './AppLayout.module.css'

const { Header, Sider, Content } = Layout

interface NavItem {
  key: string
  label: string
  icon: React.ReactNode
  path: string
}

/** Оболочка в стиле платформы: тёмное меню слева, шапка с ФИО и ролью, контент на сером фоне. */
export function AppLayout() {
  const { me, hasJournal } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md
  const [collapsed, setCollapsed] = useState(false)

  const nav: NavItem[] = useMemo(() => {
    const items: NavItem[] = [{ key: 'dashboard', label: 'Сводка', icon: <DashboardOutlined />, path: '/' }]
    if (hasJournal('medical')) {
      items.push({ key: 'medical', label: 'Медосмотры', icon: <MedicineBoxOutlined />, path: '/medical' })
    }
    if (hasJournal('technical')) {
      items.push({ key: 'technical', label: 'Техконтроль', icon: <ToolOutlined />, path: '/technical' })
    }
    return items
  }, [hasJournal])

  const selectedKey =
    nav.find((item) => item.path !== '/' && location.pathname.startsWith(item.path))?.key ??
    (location.pathname === '/' ? 'dashboard' : '')

  const go = (path: string) => {
    navigate(path)
    if (isMobile) setCollapsed(true)
  }

  const platformUser = session.platformUser()
  const fullName =
    me?.full_name ||
    [platformUser?.lastName, platformUser?.firstName, platformUser?.middleName].filter(Boolean).join(' ')
  const roleLabel = me ? roleLabels[me.role] ?? me.role : ''

  const logout = () => {
    session.clear()
    goToLogin()
  }

  const userMenu: MenuProps['items'] = [
    { key: 'profile', icon: <SettingOutlined />, label: 'Настройки профиля', onClick: () => goToPlatform('/settings/profile') },
    { key: 'logout', icon: <LogoutOutlined />, label: 'Выйти', onClick: logout },
  ]

  const siderCollapsed = collapsed && !isMobile

  return (
    <Layout className={styles.root}>
      <Sider
        trigger={null}
        collapsible
        collapsed={collapsed}
        breakpoint="md"
        collapsedWidth={isMobile ? 0 : 80}
        width={isMobile ? 280 : 240}
        className={styles.sider}
        onBreakpoint={(broken) => broken && setCollapsed(true)}
      >
        <div className={styles.logo}>
          <BrandLogo collapsed={siderCollapsed} />
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={selectedKey ? [selectedKey] : []}
          className={styles.siderMenu}
          items={nav.map((item) => ({ key: item.key, icon: item.icon, label: item.label, onClick: () => go(item.path) }))}
        />
        <div className={styles.siderFooter}>
          <Menu
            theme="dark"
            mode="inline"
            selectable={false}
            className={styles.footerMenu}
            items={[
              {
                key: 'platform',
                icon: <ArrowLeftOutlined />,
                label: 'Вернуться в Предрейс',
                onClick: () => goToPlatform(),
              },
            ]}
          />
        </div>
      </Sider>

      <Layout className={styles.mainLayout}>
        {isMobile ? (
          <div className={styles.mobileTopBar}>
            <Button
              type="text"
              className={styles.mobileTopBarBtn}
              aria-label={collapsed ? 'Открыть меню' : 'Закрыть меню'}
              icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setCollapsed(!collapsed)}
            />
            <div className={styles.mobileTopBarSpacer} />
            <Dropdown menu={{ items: userMenu }} placement="bottomRight" trigger={['click']}>
              <Button type="text" className={styles.mobileTopBarBtn} icon={<UserOutlined />} aria-label="Профиль" />
            </Dropdown>
          </div>
        ) : (
          <Header className={styles.header}>
            {fullName || roleLabel ? (
              <div className={styles.userMeta}>
                {fullName ? (
                  <Typography.Text className={styles.userName} ellipsis>
                    {fullName}
                  </Typography.Text>
                ) : null}
                {roleLabel ? <span className={styles.roleTag}>{roleLabel}</span> : null}
              </div>
            ) : null}
            <Dropdown menu={{ items: userMenu }} placement="bottomRight" trigger={['hover']}>
              <Button type="text" icon={<UserOutlined />}>
                {platformUser?.email ?? 'Профиль'}
              </Button>
            </Dropdown>
          </Header>
        )}

        <Content className={styles.content} style={{ background: brandColors.background }}>
          <Outlet />
        </Content>
      </Layout>

      {isMobile && !collapsed ? (
        <button type="button" className={styles.overlay} aria-label="Закрыть меню" onClick={() => setCollapsed(true)} />
      ) : null}
    </Layout>
  )
}
