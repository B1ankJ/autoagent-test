import {
  AppstoreOutlined,
  BulbOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  MobileOutlined,
  MoonOutlined,
  PlusOutlined,
  SettingOutlined,
  SunOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { Command } from 'cmdk'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBatches } from '../api/batches'
import { useTheme } from '../theme/useTheme'
import './CommandPalette.css'

interface Action {
  id: string
  label: string
  hint?: string
  icon: React.ReactNode
  keywords?: string
  run: () => void
}

export function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()
  const { mode, setMode } = useTheme()

  // Only query batches when the palette is open AND the user has typed
  // something — avoids a noisy GET on every keypress and on mount.
  const enabled = open && search.trim().length > 0
  const { data: batchHits } = useBatches({
    limit: 8,
    offset: 0,
    q: enabled ? search.trim() : undefined,
  })

  // Cmd-K / Ctrl-K toggle.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape' && open) {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // Linear-style "g + key" navigation. Active when NOT typing into an input.
  useEffect(() => {
    let pending = false
    let timer: number | undefined
    const navTargets: Record<string, string> = {
      d: '/',
      b: '/batches',
      p: '/profiles',
      v: '/devices',
      t: '/tests/quick',
      c: '/config',
    }
    const isTyping = (el: EventTarget | null) => {
      if (!(el instanceof HTMLElement)) return false
      const tag = el.tagName
      return (
        tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable
      )
    }
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.metaKey || e.ctrlKey || e.altKey) return
      if (open) return
      if (!pending && e.key.toLowerCase() === 'g') {
        pending = true
        timer = window.setTimeout(() => {
          pending = false
        }, 900)
        return
      }
      if (pending) {
        const target = navTargets[e.key.toLowerCase()]
        if (target) {
          e.preventDefault()
          navigate(target)
        }
        pending = false
        if (timer) window.clearTimeout(timer)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (timer) window.clearTimeout(timer)
    }
  }, [navigate, open])

  const close = () => {
    setOpen(false)
    setSearch('')
  }

  const navActions: Action[] = useMemo(
    () => [
      {
        id: 'nav-dashboard',
        label: 'Dashboard',
        hint: 'g d',
        icon: <DashboardOutlined />,
        keywords: '首页 home overview',
        run: () => navigate('/'),
      },
      {
        id: 'nav-batches',
        label: '批次 Batches',
        hint: 'g b',
        icon: <ExperimentOutlined />,
        keywords: 'batch 批次 列表',
        run: () => navigate('/batches'),
      },
      {
        id: 'nav-quick',
        label: '单次测试 Quick Test',
        hint: 'g t',
        icon: <ThunderboltOutlined />,
        keywords: 'test quick 单次',
        run: () => navigate('/tests/quick'),
      },
      {
        id: 'nav-devices',
        label: '设备 Devices',
        hint: 'g v',
        icon: <MobileOutlined />,
        keywords: 'device adb 设备',
        run: () => navigate('/devices'),
      },
      {
        id: 'nav-profiles',
        label: '配置档 Profiles',
        hint: 'g p',
        icon: <FileTextOutlined />,
        keywords: 'profile 配置 yaml',
        run: () => navigate('/profiles'),
      },
      {
        id: 'nav-builder',
        label: '配置档构建器',
        icon: <AppstoreOutlined />,
        keywords: 'builder 构建',
        run: () => navigate('/profiles/builder'),
      },
      {
        id: 'nav-config',
        label: '设置 Config',
        hint: 'g c',
        icon: <SettingOutlined />,
        keywords: 'settings 配置',
        run: () => navigate('/config'),
      },
    ],
    [navigate],
  )

  const quickActions: Action[] = useMemo(
    () => [
      {
        id: 'act-new-batch',
        label: '新建批次',
        hint: 'Create',
        icon: <PlusOutlined />,
        keywords: 'create new batch 新建',
        run: () => navigate('/batches/new'),
      },
      {
        id: 'act-theme-system',
        label: '主题：跟随系统',
        icon: <BulbOutlined />,
        keywords: 'theme system 主题',
        run: () => setMode('system'),
      },
      {
        id: 'act-theme-light',
        label: '主题：亮色',
        icon: <SunOutlined />,
        keywords: 'theme light 亮色',
        run: () => setMode('light'),
      },
      {
        id: 'act-theme-dark',
        label: '主题：暗色',
        icon: <MoonOutlined />,
        keywords: 'theme dark 暗色',
        run: () => setMode('dark'),
      },
    ],
    [navigate, setMode],
  )

  if (!open) return null

  return (
    <div
      className="aa-cmd-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close()
      }}
    >
      <Command
        label="命令面板"
        className="aa-cmd-root"
        loop
        onKeyDown={(e) => {
          if (e.key === 'Escape') close()
        }}
      >
        <div className="aa-cmd-search-row">
          <Command.Input
            value={search}
            onValueChange={setSearch}
            placeholder="搜索页面、批次、动作…"
            autoFocus
            className="aa-cmd-input"
          />
          <span className="aa-kbd">esc</span>
        </div>
        <Command.List className="aa-cmd-list">
          <Command.Empty className="aa-cmd-empty">没有匹配项</Command.Empty>

          <Command.Group heading="跳转" className="aa-cmd-group">
            {navActions.map((a) => (
              <Command.Item
                key={a.id}
                value={`${a.label} ${a.keywords ?? ''}`}
                onSelect={() => {
                  a.run()
                  close()
                }}
                className="aa-cmd-item"
              >
                <span className="aa-cmd-item-icon">{a.icon}</span>
                <span className="aa-cmd-item-label">{a.label}</span>
                {a.hint ? <span className="aa-cmd-item-hint">{a.hint}</span> : null}
              </Command.Item>
            ))}
          </Command.Group>

          <Command.Group heading="操作" className="aa-cmd-group">
            {quickActions.map((a) => (
              <Command.Item
                key={a.id}
                value={`${a.label} ${a.keywords ?? ''}`}
                onSelect={() => {
                  a.run()
                  close()
                }}
                className="aa-cmd-item"
                data-active={a.id.startsWith('act-theme-') && a.id.endsWith(mode)}
              >
                <span className="aa-cmd-item-icon">{a.icon}</span>
                <span className="aa-cmd-item-label">{a.label}</span>
                {a.hint ? <span className="aa-cmd-item-hint">{a.hint}</span> : null}
              </Command.Item>
            ))}
          </Command.Group>

          {enabled && batchHits && batchHits.length > 0 ? (
            <Command.Group heading="批次" className="aa-cmd-group">
              {batchHits.map((b) => (
                <Command.Item
                  key={b.batch_id}
                  value={`batch ${b.name} ${b.batch_id}`}
                  onSelect={() => {
                    navigate(`/batches/${b.batch_id}`)
                    close()
                  }}
                  className="aa-cmd-item"
                >
                  <span className="aa-cmd-item-icon">
                    <ExperimentOutlined />
                  </span>
                  <span className="aa-cmd-item-label">
                    {b.name}
                    <span className="aa-cmd-item-sub aa-mono"> · {b.batch_id.slice(0, 10)}</span>
                  </span>
                  <span className="aa-cmd-item-hint">{b.status}</span>
                </Command.Item>
              ))}
            </Command.Group>
          ) : null}
        </Command.List>
        <div className="aa-cmd-footer">
          <span>
            <span className="aa-kbd">↑</span>
            <span className="aa-kbd">↓</span> 选择
          </span>
          <span>
            <span className="aa-kbd">↵</span> 执行
          </span>
          <span>
            <span className="aa-kbd">g</span> + 键 快捷跳转
          </span>
        </div>
      </Command>
    </div>
  )
}
